using System.Diagnostics;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using NteHost.Input;

namespace NteHost.Input.Verifier;

/// <summary>One cleanup operation and its auditable result.</summary>
internal sealed record CleanupStep(string Name, bool Ok, bool Skipped, string Reason);

internal readonly record struct CleanupActionResult(bool Ok, bool Skipped, string Reason)
{
    public static CleanupActionResult Success(string reason = "OK") => new(true, false, reason);

    public static CleanupActionResult Failure(string reason) => new(false, false, reason);

    public static CleanupActionResult Skip(string reason) => new(true, true, reason);
}

internal readonly record struct TakeoverReadResult(bool Ok, bool Seen, string Reason)
{
    public static TakeoverReadResult Success(bool seen, string reason = "OK") => new(true, seen, reason);

    public static TakeoverReadResult Failure(string reason) => new(false, false, reason);
}

internal sealed record TakeoverCheck(string Stage, bool Ok, bool Seen, string Reason, long MonotonicNs);

internal sealed class CleanupReceipt
{
    public CleanupReceipt(string id, string description)
    {
        Id = id;
        Description = description;
    }

    public string Id { get; }

    public string Description { get; }

    public bool UserTakeover { get; set; }

    public bool Passed { get; set; } = true;

    public string FailureReason { get; set; } = string.Empty;

    public List<string> Order { get; } = new();

    public List<CleanupStep> Steps { get; } = new();

    public List<TakeoverCheck> TakeoverChecks { get; } = new();

    public bool TakeoverReadFailed { get; private set; }

    public void Add(string name, bool ok, bool skipped, string reason)
    {
        Order.Add(name);
        Steps.Add(new CleanupStep(name, ok, skipped, reason));
        if (!ok)
        {
            Passed = false;
            if (string.IsNullOrEmpty(FailureReason))
            {
                FailureReason = reason;
            }
        }
    }

    public void AddTakeoverCheck(string stage, TakeoverReadResult read)
    {
        TakeoverChecks.Add(new TakeoverCheck(stage, read.Ok, read.Seen, read.Reason, TraceClock.NowNs()));
        if (!read.Ok)
        {
            TakeoverReadFailed = true;
            Passed = false;
            if (string.IsNullOrEmpty(FailureReason))
            {
                FailureReason = read.Reason;
            }
        }
    }

    public JsonObject ToJson()
    {
        var steps = new JsonArray();
        foreach (CleanupStep step in Steps)
        {
            steps.Add(J.Obj(
                ("name", J.N(step.Name)),
                ("ok", J.N(step.Ok)),
                ("skipped", J.N(step.Skipped)),
                ("reason", J.N(step.Reason))));
        }

        var takeoverChecks = new JsonArray();
        foreach (TakeoverCheck check in TakeoverChecks)
        {
            takeoverChecks.Add(J.Obj(
                ("stage", J.N(check.Stage)),
                ("ok", J.N(check.Ok)),
                ("seen", J.N(check.Seen)),
                ("reason", J.N(check.Reason)),
                ("monotonicNs", J.N(check.MonotonicNs))));
        }

        return J.Obj(
            ("id", J.N(Id)),
            ("description", J.N(Description)),
            ("userTakeover", J.N(UserTakeover)),
            ("status", J.N(Passed ? "PASS" : "FAIL")),
            ("failureReason", J.N(FailureReason)),
            ("takeoverReadFailed", J.N(TakeoverReadFailed)),
            ("order", new JsonArray(Order.Select(J.N).ToArray())),
            ("steps", steps),
            ("takeoverChecks", takeoverChecks));
    }
}

/// <summary>
/// The only cleanup owner used by both fake cleanup verification and the live
/// path.  The callbacks are deliberately split so the policy is visible:
/// release/stop new actions first, then cursor policy, observer stop, window
/// shutdown, foreground policy, and finally safe synchronization disposal.
/// </summary>
internal sealed class CleanupSurface
{
    public required Func<CleanupActionResult> StopNewActions { get; init; }

    public required Func<TakeoverReadResult> ReadTakeover { get; init; }

    public required Func<CleanupActionResult> RestoreCursorWithoutTakeover { get; init; }

    public required Func<CleanupActionResult> PreserveUserCursor { get; init; }

    public required Func<CleanupActionResult> StopObserver { get; init; }

    public required Func<CleanupActionResult> ShutdownWindow { get; init; }

    public required Func<CleanupActionResult> RestoreForegroundWithoutTakeover { get; init; }

    public required Func<CleanupActionResult> PreserveUserForeground { get; init; }

    public required Func<bool> WindowThreadAlive { get; init; }

    public required Func<CleanupActionResult> DisposeSynchronizationIfSafe { get; init; }
}

internal static class CleanupCoordinator
{
    public static CleanupReceipt Run(string id, string description, CleanupSurface surface)
    {
        var receipt = new CleanupReceipt(id, description);

        Invoke(receipt, "stop_new_actions", surface.StopNewActions);
        TakeoverReadResult afterStop = ReadTakeover(receipt, surface.ReadTakeover, "after_stop_new_actions");
        receipt.UserTakeover = afterStop.Ok && afterStop.Seen;

        if (!afterStop.Ok)
        {
            // An unreadable monitor is fail-closed.  It is never interpreted as
            // "no takeover", and both recovery operations are skipped.
            receipt.Add(
                "cursor_restore_original",
                ok: false,
                skipped: true,
                "TAKEOVER_STATE_READ_FAILED_SKIP_CURSOR_RESTORE");
        }
        else if (receipt.UserTakeover)
        {
            // The guard has already made the takeover decision.  Harness cleanup
            // only observes/preserves the current cursor and never calls SetCursorPos.
            Invoke(receipt, "cursor_preserve_user", surface.PreserveUserCursor);
        }
        else
        {
            // The harness is the sole owner of the original pre-window cursor in
            // this runner.  The guard is configured not to duplicate this restore.
            Invoke(receipt, "cursor_restore_original", surface.RestoreCursorWithoutTakeover);
        }

        // Foreground recovery remains while the observer is alive.  A new input
        // event after cursor processing therefore cancels the still-uncommitted
        // foreground recovery instead of being hidden by teardown.
        TakeoverReadResult beforeForeground = ReadTakeover(receipt, surface.ReadTakeover, "before_foreground_recovery");
        if (!beforeForeground.Ok)
        {
            receipt.Add(
                "foreground_restore_original",
                ok: false,
                skipped: true,
                "TAKEOVER_STATE_READ_FAILED_SKIP_FOREGROUND_RESTORE");
        }
        else if (beforeForeground.Seen)
        {
            receipt.UserTakeover = true;
            Invoke(receipt, "foreground_preserve_user", surface.PreserveUserForeground);
        }
        else
        {
            Invoke(receipt, "foreground_restore_original", surface.RestoreForegroundWithoutTakeover);
        }

        // All recovery decisions are complete before observer/window teardown.
        Invoke(receipt, "observer_stop", surface.StopObserver);
        Invoke(receipt, "window_shutdown_and_wait", surface.ShutdownWindow);

        bool threadAlive = SafeBoolCall(surface.WindowThreadAlive);
        if (threadAlive)
        {
            receipt.Add(
                "sync_dispose",
                ok: false,
                skipped: true,
                "WINDOW_THREAD_EXIT_TIMEOUT_SYNC_DISPOSE_BLOCKED");
        }
        else
        {
            Invoke(receipt, "sync_dispose", surface.DisposeSynchronizationIfSafe);
        }

        return receipt;
    }

    private static void Invoke(CleanupReceipt receipt, string name, Func<CleanupActionResult> operation)
    {
        CleanupActionResult result = SafeCall(operation);
        receipt.Add(name, result.Ok, result.Skipped, string.IsNullOrEmpty(result.Reason)
            ? (result.Ok ? "OK" : "FAILED")
            : result.Reason);
    }

    private static CleanupActionResult SafeCall(Func<CleanupActionResult> operation)
    {
        try
        {
            return operation();
        }
        catch (Exception ex)
        {
            return CleanupActionResult.Failure("EXCEPTION:" + ex.GetType().Name);
        }
    }

    private static bool SafeBoolCall(Func<bool> operation)
    {
        try
        {
            return operation();
        }
        catch
        {
            return true;
        }
    }

    private static TakeoverReadResult ReadTakeover(
        CleanupReceipt receipt,
        Func<TakeoverReadResult> read,
        string stage)
    {
        TakeoverReadResult result;
        try
        {
            result = read();
        }
        catch (Exception ex)
        {
            result = TakeoverReadResult.Failure("TAKEOVER_STATE_READ_EXCEPTION:" + ex.GetType().Name);
        }

        receipt.AddTakeoverCheck(stage, result);
        return result;
    }
}

internal sealed class CleanupCaseResult
{
    private readonly List<string> _assertions = new();
    private readonly List<string> _failures = new();

    public CleanupCaseResult(string id, string description)
    {
        Id = id;
        Description = description;
    }

    public string Id { get; }

    public string Description { get; }

    public CleanupReceipt? Receipt { get; set; }

    public string Note { get; set; } = string.Empty;

    public bool Passed => _failures.Count == 0;

    public void Check(bool condition, string description)
    {
        _assertions.Add($"{(condition ? "PASS" : "FAIL")}: {description}");
        if (!condition)
        {
            _failures.Add(description);
        }
    }

    public JsonObject ToJson()
    {
        var assertions = new JsonArray(_assertions.Select(J.N).ToArray());
        var failures = new JsonArray(_failures.Select(J.N).ToArray());
        return J.Obj(
            ("id", J.N(Id)),
            ("description", J.N(Description)),
            ("status", J.N(Passed ? "PASS" : "FAIL")),
            ("note", J.N(Note)),
            ("receipt", Receipt?.ToJson()),
            ("assertions", assertions),
            ("failures", failures));
    }
}

/// <summary>Pure fake surface used to test cleanup policy without Win32 calls.</summary>
internal sealed class FakeCleanupState
{
    public bool UserTakeover { get; init; }

    public bool TakeoverReadThrows { get; init; }

    public bool CursorRestoreReturns { get; init; } = true;

    public bool CursorReadReturns { get; init; } = true;

    public bool ObserverStopReturns { get; init; } = true;

    public bool WindowExitReturns { get; init; } = true;

    public bool ForegroundRestoreReturns { get; init; } = true;

    public (int X, int Y) OriginalCursor { get; } = (10, 10);

    public (int X, int Y) CurrentCursor { get; private set; } = (50, 60);

    public int CursorSetCalls { get; private set; }

    public int ForegroundSetCalls { get; private set; }

    public bool SynchronizationDisposed { get; private set; }

    public Action? AfterStopNewActions { get; set; }

    public Action? AfterCursorRestore { get; set; }

    private bool _takeoverSeen;

    public bool ThreadAlive => !WindowExitReturns;

    public void RecordTakeover() => _takeoverSeen = true;

    public CleanupActionResult ReleaseGuard()
    {
        // The fake guard has already classified takeover.  It never performs the
        // harness-owned original-cursor restore in this policy configuration.
        AfterStopNewActions?.Invoke();
        return CleanupActionResult.Success();
    }

    public TakeoverReadResult ReadTakeover()
    {
        if (TakeoverReadThrows)
        {
            throw new InvalidOperationException("Injected takeover monitor read failure.");
        }

        return TakeoverReadResult.Success(_takeoverSeen || UserTakeover);
    }

    public CleanupActionResult RestoreCursorWithoutTakeover()
    {
        CursorSetCalls++;
        if (!CursorRestoreReturns || !CursorReadReturns)
        {
            return CleanupActionResult.Failure(!CursorRestoreReturns
                ? "CURSOR_RESTORE_RETURN_FALSE"
                : "CURRENT_CURSOR_READ_FAILED");
        }

        CurrentCursor = OriginalCursor;
        AfterCursorRestore?.Invoke();
        return CleanupActionResult.Success("CURSOR_RESTORE_OK");
    }

    public CleanupActionResult PreserveUserCursor()
    {
        // A preserve operation is read-only.  It is intentionally false if the
        // fake cannot perform the required verification read.
        return CursorReadReturns && CursorSetCalls == 0
            ? CleanupActionResult.Skip("CURSOR_RESTORE_USER_TAKEOVER")
            : CleanupActionResult.Failure("CURRENT_CURSOR_READ_FAILED");
    }

    public CleanupActionResult StopObserver() => ObserverStopReturns
        ? CleanupActionResult.Success()
        : CleanupActionResult.Failure("OBSERVER_STOP_FAILED");

    public CleanupActionResult ShutdownWindow() => WindowExitReturns
        ? CleanupActionResult.Success("WINDOW_THREAD_EXITED")
        : CleanupActionResult.Failure("WINDOW_THREAD_EXIT_TIMEOUT");

    public CleanupActionResult RestoreForegroundWithoutTakeover()
    {
        ForegroundSetCalls++;
        return ForegroundRestoreReturns
            ? CleanupActionResult.Success("FOREGROUND_RESTORE_OK")
            : CleanupActionResult.Failure("FOREGROUND_RESTORE_FAILED");
    }

    public CleanupActionResult PreserveUserForeground() => CleanupActionResult.Skip("FOREGROUND_RESTORE_USER_TAKEOVER");

    public CleanupActionResult DisposeSynchronizationIfSafe()
    {
        if (ThreadAlive)
        {
            return CleanupActionResult.Failure("WINDOW_THREAD_EXIT_TIMEOUT_SYNC_DISPOSE_BLOCKED");
        }

        SynchronizationDisposed = true;
        return CleanupActionResult.Success();
    }
}

/// <summary>Deterministic foreground surface used by the verifier-only matrix.</summary>
internal sealed class FakeForegroundRestoreSurface
{
    public IntPtr OriginalWindow { get; } = new(100);

    public IntPtr OtherWindow { get; } = new(200);

    public IntPtr CurrentForeground { get; private set; } = new(200);

    public bool OriginalWindowValid { get; set; } = true;

    public bool SetForegroundReturns { get; set; } = true;

    /// <summary>Number of confirmation reads that remain non-original after a request.</summary>
    public int? ConfirmAfterReads { get; set; }

    /// <summary>Number of normal NULL results returned after a request.</summary>
    public int? NullForegroundReads { get; set; }

    public bool AlwaysReturnNullDuringConfirmation { get; set; }

    public bool ThrowDuringConfirmationRead { get; set; }

    public int SetForegroundCalls { get; private set; }

    public int ForegroundReadCalls { get; private set; }

    public bool IsWindow(IntPtr window) => OriginalWindowValid && window == OriginalWindow;

    public IntPtr GetForegroundWindow()
    {
        ForegroundReadCalls++;
        if (SetForegroundCalls > 0 && ThrowDuringConfirmationRead)
        {
            throw new InvalidOperationException("FAKE_FOREGROUND_READ_EXCEPTION");
        }

        if (SetForegroundCalls > 0 && AlwaysReturnNullDuringConfirmation)
        {
            return IntPtr.Zero;
        }

        if (SetForegroundCalls > 0 && NullForegroundReads is { } nullReads && nullReads > 0)
        {
            NullForegroundReads = nullReads - 1;
            return IntPtr.Zero;
        }

        if (SetForegroundCalls > 0 && ConfirmAfterReads is { } remaining)
        {
            if (remaining == 0)
            {
                CurrentForeground = OriginalWindow;
            }
            else
            {
                ConfirmAfterReads = remaining - 1;
            }
        }

        return CurrentForeground;
    }

    public bool SetForegroundWindow(IntPtr window)
    {
        SetForegroundCalls++;
        if (!SetForegroundReturns)
        {
            return false;
        }

        return window == OriginalWindow;
    }
}

internal sealed class LiveEventRecorder
{
    private readonly object _gate = new();
    private readonly List<JsonObject> _records = new();
    private long _ordinal;

    public void Record(string scenario, string type, params (string Key, JsonNode? Value)[] fields)
    {
        var pairs = new List<(string Key, JsonNode? Value)>
        {
            ("ordinal", J.N(Interlocked.Increment(ref _ordinal))),
            ("monotonicNs", J.N(TraceClock.NowNs())),
            ("scenario", J.N(scenario)),
            ("type", J.N(type)),
        };
        pairs.AddRange(fields);
        JsonObject item = J.Obj(pairs.ToArray());
        lock (_gate)
        {
            _records.Add(item);
        }
    }

    public void RecordTrace(string scenario, string phase, string detail)
    {
        Record(
            scenario,
            "guard_trace",
            ("phase", J.N(phase)),
            ("detail", J.N(detail)));
    }

    public void RecordObserved(string scenario, in ObservedInputEvent observed)
    {
        Record(
            scenario,
            "observed_input",
             ("kind", J.N(observed.Kind.ToString())),
             ("device", J.N(observed.Device.ToString())),
             ("origin", J.N(observed.Origin.ToString())),
             ("classification", J.N(observed.Origin.ToString())),
             ("nativeFlags", observed.Device == InputDeviceClass.Mouse
                 ? J.N((long)observed.NativeFlags)
                 : null),
             ("nativeFlagsHex", observed.Device == InputDeviceClass.Mouse
                 ? J.N(J.Hex(observed.NativeFlags))
                 : null),
             ("extraInfo", J.N(observed.ExtraInfo)),
            ("extraInfoHex", J.N(J.Hex(observed.ExtraInfo))),
            ("x", J.N(observed.X)),
            ("y", J.N(observed.Y)),
            ("sourceMonotonicNs", J.N(observed.MonotonicNs)),
            ("sourceSequence", J.N(observed.Sequence)));
    }

    public void RecordCleanup(string scenario, CleanupReceipt receipt) =>
        Record(scenario, "cleanup_receipt", ("receipt", receipt.ToJson()));

    public IReadOnlyList<JsonObject> Snapshot()
    {
        lock (_gate)
        {
            return _records.Select(record => (JsonObject)record.DeepClone()).ToArray();
        }
    }
}

internal sealed class LiveTakeoverRecorder
{
    private readonly object _gate = new();
    private readonly Func<ulong> _trustedMarker;
    private readonly List<ObservedInputEvent> _events = new();
    private bool _takeoverSeen;
    private bool _readFailure;

    public LiveTakeoverRecorder(Func<ulong> trustedMarker)
    {
        _trustedMarker = trustedMarker;
    }

    public bool HasHardwareMouseMove
    {
        get
        {
            lock (_gate)
            {
                return _events.Any(observed => IsHardwareMouseMove(observed));
            }
        }
    }

    public ObservedInputEvent? FirstHardwareMouseMove
    {
        get
        {
            lock (_gate)
            {
                foreach (ObservedInputEvent observed in _events)
                {
                    if (IsHardwareMouseMove(observed))
                    {
                        return observed;
                    }
                }

                return null;
            }
        }
    }

    public bool HasHardwareMouseMoveAfter(long monotonicNs) =>
        FirstHardwareMouseMoveAfter(monotonicNs) is not null;

    public ObservedInputEvent? FirstHardwareMouseMoveAfter(long monotonicNs)
    {
        lock (_gate)
        {
            foreach (ObservedInputEvent observed in _events)
            {
                if (observed.MonotonicNs >= monotonicNs && IsHardwareMouseMove(observed))
                {
                    return observed;
                }
            }

            return null;
        }
    }

    public ObservedInputEvent? LastHardwareMouseMoveAfter(long monotonicNs)
    {
        lock (_gate)
        {
            ObservedInputEvent? last = null;
            foreach (ObservedInputEvent observed in _events)
            {
                if (observed.MonotonicNs >= monotonicNs && IsHardwareMouseMove(observed))
                {
                    last = observed;
                }
            }

            return last;
        }
    }

    public int EventCount
    {
        get { lock (_gate) { return _events.Count; } }
    }

    public IReadOnlyList<ObservedInputEvent> SnapshotEvents()
    {
        lock (_gate)
        {
            return _events.ToArray();
        }
    }

    public void Record(in ObservedInputEvent observed)
    {
        lock (_gate)
        {
            _events.Add(observed);
            if (IsPotentialTakeover(observed))
            {
                _takeoverSeen = true;
            }
        }
    }

    public TakeoverReadResult Read()
    {
        lock (_gate)
        {
            if (_readFailure)
            {
                return TakeoverReadResult.Failure("TAKEOVER_STATE_READ_FAILED");
            }

            return TakeoverReadResult.Success(_takeoverSeen, "TAKEOVER_STATE_READ_OK");
        }
    }

    public void InjectReadFailureForFake() => _readFailure = true;

    private bool IsPotentialTakeover(in ObservedInputEvent observed)
    {
        return observed.Origin != InputEventOrigin.Injected ||
               !InputMarker.ExactMatch(_trustedMarker(), observed.ExtraInfo);
    }

    private static bool IsHardwareMouseMove(in ObservedInputEvent observed) =>
        observed.Kind == InputEventKind.MouseMove &&
        observed.Device == InputDeviceClass.Mouse &&
        observed.Origin == InputEventOrigin.Hardware;
}

internal sealed class BarrierTraceSink : IInputTraceSink
{
    private readonly string? _blockedPhase;
    private readonly TimeSpan _wait;
    private readonly LiveEventRecorder _recorder;
    private readonly string _scenario;
    private Func<CancelOutcome>? _timeoutCancellation;
    private int _waitTimedOut;

    public BarrierTraceSink(
        string? blockedPhase,
        TimeSpan wait,
        LiveEventRecorder recorder,
        string scenario)
    {
        _blockedPhase = blockedPhase;
        _wait = wait;
        _recorder = recorder;
        _scenario = scenario;
    }

    public InMemoryInputTraceSink Inner { get; } = new();

    public ManualResetEventSlim Reached { get; } = new(false);

    public ManualResetEventSlim Continue { get; } = new(false);

    public bool WaitTimedOut => Volatile.Read(ref _waitTimedOut) != 0;

    public void SetTimeoutCancellation(Func<CancelOutcome> timeoutCancellation)
    {
        _timeoutCancellation = timeoutCancellation ?? throw new ArgumentNullException(nameof(timeoutCancellation));
    }

    public void Write(string phase, string detail)
    {
        Inner.Write(phase, detail);
        _recorder.RecordTrace(_scenario, phase, detail);
        if (_blockedPhase is not null && string.Equals(phase, _blockedPhase, StringComparison.Ordinal))
        {
            Reached.Set();
            if (!Continue.Wait(_wait))
            {
                Interlocked.Exchange(ref _waitTimedOut, 1);
                CancelOutcome? cancellation = _timeoutCancellation?.Invoke();
                _recorder.Record(
                    _scenario,
                    "barrier_timeout",
                    ("phase", J.N(phase)),
                    ("cancelIssued", J.N(cancellation is not null)),
                    ("cancelOk", J.N(cancellation?.Ok ?? false)),
                    ("cancelAlreadyApplied", J.N(cancellation?.AlreadyCancelled ?? false)),
                    ("cancelReason", J.N(cancellation?.Reason ?? "BARRIER_CANCEL_CALLBACK_MISSING")));

                // A missing/failed cancellation callback is an infrastructure
                // failure.  Never return normally from the barrier in that case:
                // normal return is the path that would reach prepare/send.
                if (cancellation is null || (!cancellation.Ok && !cancellation.AlreadyCancelled))
                {
                    throw new InvalidOperationException("BARRIER_TIMEOUT_CANCELLATION_FAILED");
                }
            }
        }
    }
}

/// <summary>
/// Explicitly gated live runner plus fake-only cleanup verification.  Merely
/// starting the verifier, or passing --offline-cleanup, cannot construct a live
/// window, hook, cursor backend, or raw backend.
/// </summary>
internal static class LiveRunner
{
    private const string AcceptedOfflineHead = "7c4c21b45fc54412814519974aab25be226e3f1f";
    private const string BaselineCommit = "a9b52c6fb8db3c5f7dbfb2e80cb5a32bb4a526e9";
    private const int ObserverStopTimeoutMs = 2000;
    private const int WindowStopTimeoutMs = 2000;
    private const int DefaultManualTimeoutMs = 10000;
    private const int ForegroundRestoreConfirmationTimeoutMs = 1500;
    private const int ForegroundRestorePollMs = 10;
    private const int MaxSuccessfulRawCalls = 3;
    private const string OfflineReviewJudgementVersion = "v2.2b.l5.program-noninterference.v2";

    public static int RunOfflineCleanup(string[] args)
    {
        string repoRoot = FindRepositoryRoot();
        string output = Path.GetFullPath(ParseOutputDirectory(args, "build/v2-2b-live/cleanup-evidence"), repoRoot);
        EnsureOutputDirectoryIsEmpty(output);

        var cases = new List<CleanupCaseResult>
        {
            RunCleanupCase("CL01", "no takeover restores original cursor before observer teardown", () =>
            {
                var fake = new FakeCleanupState();
                CleanupReceipt receipt = RunFakeCleanup(fake, "clean restore");
                var result = new CleanupCaseResult("CL01", "no takeover restores original cursor before observer teardown")
                {
                    Receipt = receipt,
                };
                result.Check(receipt.Passed, "clean cleanup passes");
                result.Check(fake.CursorSetCalls == 1, "harness restores cursor exactly once");
                result.Check(fake.CurrentCursor == fake.OriginalCursor, "final cursor equals original cursor");
                result.Check(OrderIs(receipt, "cursor_restore_original", "foreground_restore_original", "observer_stop", "window_shutdown_and_wait"),
                    "cursor and foreground policy complete before observer and window teardown");
                result.Check(fake.SynchronizationDisposed, "synchronization is disposed after thread exit");
                return result;
            }),
            RunCleanupCase("CL02", "takeover preserves user cursor and foreground", () =>
            {
                var fake = new FakeCleanupState { UserTakeover = true };
                CleanupReceipt receipt = RunFakeCleanup(fake, "takeover preserve");
                var result = new CleanupCaseResult("CL02", "takeover preserves user cursor and foreground")
                {
                    Receipt = receipt,
                };
                result.Check(receipt.Passed, "takeover cleanup passes");
                result.Check(fake.CursorSetCalls == 0, "takeover path makes no cursor set call");
                result.Check(fake.CurrentCursor == (50, 60), "user cursor position is preserved");
                result.Check(fake.ForegroundSetCalls == 0, "takeover path does not restore old foreground");
                result.Check(receipt.UserTakeover, "receipt records takeover branch");
                return result;
            }),
            RunCleanupCase("CL03", "original-state read failure aborts before controlled window creation", () =>
            {
                var result = new CleanupCaseResult("CL03", "original-state read failure aborts before controlled window creation");
                bool created = false;
                bool foregroundRead = false;
                string reason = CaptureOriginalStateForFake(foregroundRead, cursorRead: true, ref created);
                result.Check(reason == "ORIGINAL_FOREGROUND_READ_FAILED", "foreground read failure is explicit");
                result.Check(!created, "controlled window is not created after preflight read failure");
                return result;
            }),
            RunCleanupCase("CL04", "cursor restore false is a cleanup failure with final position evidence", () =>
            {
                var fake = new FakeCleanupState { CursorRestoreReturns = false };
                CleanupReceipt receipt = RunFakeCleanup(fake, "restore returns false");
                var result = new CleanupCaseResult("CL04", "cursor restore false is a cleanup failure with final position evidence")
                {
                    Receipt = receipt,
                };
                result.Check(!receipt.Passed, "restore false prevents cleanup PASS");
                result.Check(fake.CursorSetCalls == 1, "restore was attempted once");
                result.Check(fake.CurrentCursor == (50, 60), "failed restore does not claim original coordinates");
                result.Check(receipt.Steps.Any(step => step.Name == "cursor_restore_original" && !step.Ok),
                    "restore failure is recorded as a failed step");
                return result;
            }),
            RunCleanupCase("CL05", "cursor read failure is not replaced with a sentinel coordinate", () =>
            {
                var fake = new FakeCleanupState { CursorReadReturns = false };
                CleanupReceipt receipt = RunFakeCleanup(fake, "restore read failure");
                var result = new CleanupCaseResult("CL05", "cursor read failure is not replaced with a sentinel coordinate")
                {
                    Receipt = receipt,
                };
                result.Check(!receipt.Passed, "read failure prevents cleanup PASS");
                result.Check(fake.CurrentCursor == (50, 60), "failed read does not synthesize (0,0) success");
                return result;
            }),
            RunCleanupCase("CL06", "window thread timeout blocks synchronization disposal", () =>
            {
                var fake = new FakeCleanupState { WindowExitReturns = false };
                CleanupReceipt receipt = RunFakeCleanup(fake, "thread timeout");
                var result = new CleanupCaseResult("CL06", "window thread timeout blocks synchronization disposal")
                {
                    Receipt = receipt,
                };
                result.Check(!receipt.Passed, "thread timeout prevents cleanup PASS");
                result.Check(receipt.Steps.Any(step => step.Name == "sync_dispose" && step.Skipped && !step.Ok),
                    "sync disposal is blocked while thread is alive");
                result.Check(!fake.SynchronizationDisposed, "synchronization is not released after timeout");
                return result;
            }),
            RunCleanupCase("CL07", "takeover after release is observed before cursor recovery", () =>
            {
                var fake = new FakeCleanupState();
                fake.AfterStopNewActions = fake.RecordTakeover;
                CleanupReceipt receipt = RunFakeCleanup(fake, "release then takeover");
                var result = new CleanupCaseResult("CL07", "takeover after release is observed before cursor recovery")
                {
                    Receipt = receipt,
                };
                result.Check(receipt.Passed, "late takeover is handled as a safe preserve branch");
                result.Check(receipt.UserTakeover, "takeover after Release is recorded");
                result.Check(fake.CursorSetCalls == 0, "cursor restore is cancelled before commit");
                result.Check(fake.ForegroundSetCalls == 0, "foreground restore is cancelled");
                result.Check(receipt.TakeoverChecks.Any(check => check.Stage == "after_stop_new_actions" && check.Seen),
                    "monitor sees takeover after guard Release");
                return result;
            }),
            RunCleanupCase("CL08", "takeover after cursor handling cancels foreground recovery", () =>
            {
                var fake = new FakeCleanupState();
                fake.AfterCursorRestore = fake.RecordTakeover;
                CleanupReceipt receipt = RunFakeCleanup(fake, "takeover after cursor");
                var result = new CleanupCaseResult("CL08", "takeover after cursor handling cancels foreground recovery")
                {
                    Receipt = receipt,
                };
                result.Check(receipt.Passed, "late foreground takeover is handled safely");
                result.Check(fake.CursorSetCalls == 1, "cursor recovery already committed exactly once");
                result.Check(fake.CurrentCursor == fake.OriginalCursor, "committed cursor recovery is auditable");
                result.Check(fake.ForegroundSetCalls == 0, "foreground recovery is cancelled after the new takeover");
                result.Check(receipt.TakeoverChecks.Any(check => check.Stage == "before_foreground_recovery" && check.Seen),
                    "monitor sees takeover after cursor processing");
                return result;
            }),
            RunCleanupCase("CL09", "takeover monitor read failure skips both recoveries", () =>
            {
                var fake = new FakeCleanupState { TakeoverReadThrows = true };
                CleanupReceipt receipt = RunFakeCleanup(fake, "takeover read failure");
                var result = new CleanupCaseResult("CL09", "takeover monitor read failure skips both recoveries")
                {
                    Receipt = receipt,
                };
                result.Check(!receipt.Passed, "monitor read failure prevents cleanup PASS");
                result.Check(receipt.TakeoverReadFailed, "monitor read failure is recorded");
                result.Check(fake.CursorSetCalls == 0 && fake.ForegroundSetCalls == 0,
                    "read failure does not fall back to restoration");
                result.Check(receipt.Steps.Any(step => step.Name == "cursor_restore_original" && step.Skipped),
                    "cursor recovery is explicitly skipped");
                result.Check(receipt.Steps.Any(step => step.Name == "foreground_restore_original" && step.Skipped),
                    "foreground recovery is explicitly skipped");
                return result;
            }),
            RunCleanupCase("CL10", "injectable L5 runner requires hardware mouse move and preserves its position", RunFakeManualL5Case),
            RunCleanupCase("CL11", "multiple hardware moves during cleanup preserve user position", RunFakeManualL5MovingDuringCleanupCase),
            RunCleanupCase("LF01", "injectable L4 distinguishes guard prepare/restore from harness cleanup restore", RunFakePreparedL4Case),
            RunCleanupCase("BF01", "barrier timeout cancels before prepare with no input event", RunFakeBarrierTimeoutCase),
            RunCleanupCase("BF02", "late observer thread cannot reopen a timed-out barrier", RunFakeBarrierDelayedInputCase),
            RunCleanupCase("FG01", "foreground request rejection is diagnosed without confirmation", RunFakeForegroundRequestRejectedCase),
            RunCleanupCase("FG02", "foreground confirmation timeout is bounded and diagnosed", RunFakeForegroundConfirmationTimeoutCase),
            RunCleanupCase("FG03", "invalid original foreground is diagnosed before request", RunFakeOriginalForegroundInvalidCase),
            RunCleanupCase("FG04", "foreground confirmation waits for delayed success", RunFakeForegroundDelayedSuccessCase),
            RunCleanupCase("FG05", "takeover during foreground confirmation stops recovery", RunFakeForegroundTakeoverCase),
            RunCleanupCase("FG06", "takeover read failure during foreground confirmation stops recovery", RunFakeForegroundReadFailureCase),
            RunCleanupCase("FG07", "normal NULL foreground result waits for target confirmation", RunFakeForegroundNullThenTargetCase),
            RunCleanupCase("FG08", "continuous NULL foreground results time out", RunFakeForegroundNullTimeoutCase),
            RunCleanupCase("FG09", "takeover during NULL foreground wait stops recovery", RunFakeForegroundNullTakeoverCase),
            RunCleanupCase("FG10", "foreground read exception is diagnosed separately", RunFakeForegroundReadExceptionCase),
            RunCleanupCase("FG11", "initial NULL foreground capture prevents test start", RunFakeInitialForegroundNullCase),
        };

        bool allPassed = cases.All(item => item.Passed);
        WriteCleanupEvidence(repoRoot, output, cases, allPassed);
        int passed = cases.Count(item => item.Passed);
        Console.WriteLine($"V2-2B CLEANUP OFFLINE {(allPassed ? "PASS" : "FAIL")}: {passed}/{cases.Count} cases");
        Console.WriteLine($"Evidence: {Path.Combine(output, "cleanup_manifest.json")}");
        return allPassed ? 0 : 1;
    }

    public static int RunOfflineLiveReview(string[] args)
    {
        string repoRoot = FindRepositoryRoot();
        string input = Path.GetFullPath(ParseRequiredDirectory(args, "--input"), repoRoot);
        string output = Path.GetFullPath(ParseOutputDirectory(args, "build/v2-2b-offline/l5-diagnostic-erratum-r1"), repoRoot);
        EnsureOutputDirectoryIsEmpty(output);

        string[] sourceNames =
        {
            "live_raw.ndjson",
            "live_matrix.json",
            "live_summary.json",
            "live_summary.md",
            "live_manifest.json",
        };
        foreach (string name in sourceNames)
        {
            if (!File.Exists(Path.Combine(input, name)))
            {
                throw new FileNotFoundException("Original live evidence file is missing: " + name, Path.Combine(input, name));
            }
        }

        string sourceManifestPath = Path.Combine(input, "live_manifest.json");
        string sourceSummaryPath = Path.Combine(input, "live_summary.json");
        JsonObject sourceManifest = JsonNode.Parse(File.ReadAllText(sourceManifestPath))?.AsObject()
            ?? throw new InvalidDataException("Original live manifest is not a JSON object.");
        JsonObject sourceSummary = JsonNode.Parse(File.ReadAllText(sourceSummaryPath))?.AsObject()
            ?? throw new InvalidDataException("Original live summary is not a JSON object.");
        JsonObject sourceScenario = FindScenario(sourceSummary, "L5");
        JsonObject sourceCleanup = RequiredObject(sourceScenario, "cleanup");
        JsonObject sourcePhysicalMove = RequiredObject(sourceScenario, "physicalMouseMove");

        string sourceHead = RequiredString(sourceSummary, "headCommit");
        string manifestHead = RequiredString(sourceManifest, "headCommit");
        string currentHead = GitValue(repoRoot, "rev-parse", "HEAD");
        string sourceOriginalStatus = RequiredString(sourceScenario, "status");
        string sourceOriginalReason = RequiredString(sourceScenario, "reason");

        JsonArray declaredSource = sourceManifest["declaredArtifacts"]?.AsArray()
            ?? throw new InvalidDataException("Original live manifest has no declaredArtifacts.");
        JsonArray expectedSource = sourceManifest["expectedArtifacts"]?.AsArray()
            ?? throw new InvalidDataException("Original live manifest has no expectedArtifacts.");
        var declaredByName = new Dictionary<string, JsonObject>(StringComparer.OrdinalIgnoreCase);
        foreach (JsonNode? item in declaredSource)
        {
            if (item is JsonObject artifact && artifact["name"]?.GetValue<string>() is { } name)
            {
                declaredByName[name] = artifact;
            }
        }

        string[] expectedNames = expectedSource
            .Select(item => item?.GetValue<string>() ?? string.Empty)
            .Where(name => !string.IsNullOrEmpty(name))
            .ToArray();
        string[] actualNames = Directory.GetFiles(input, "*", SearchOption.TopDirectoryOnly)
            .Select(Path.GetFileName)
            .Where(name => name is not null)
            .Cast<string>()
            .OrderBy(name => name, StringComparer.OrdinalIgnoreCase)
            .ToArray();
        string[] expectedWithManifest = expectedNames
            .Append("live_manifest.json")
            .OrderBy(name => name, StringComparer.OrdinalIgnoreCase)
            .ToArray();

        var sourceArtifacts = new JsonArray();
        bool sourceArtifactsMatch = true;
        foreach (string name in sourceNames)
        {
            string path = Path.Combine(input, name);
            var info = new FileInfo(path);
            string hash = Sha256(path);
            bool declared = declaredByName.TryGetValue(name, out JsonObject? entry);
            bool sizeMatches = name.Equals("live_manifest.json", StringComparison.OrdinalIgnoreCase) ||
                               declared && entry!["sizeBytes"]?.GetValue<long>() == info.Length;
            bool hashMatches = name.Equals("live_manifest.json", StringComparison.OrdinalIgnoreCase) ||
                               declared && string.Equals(entry!["sha256"]?.GetValue<string>(), hash, StringComparison.OrdinalIgnoreCase);
            sourceArtifactsMatch &= declared || name.Equals("live_manifest.json", StringComparison.OrdinalIgnoreCase);
            sourceArtifactsMatch &= sizeMatches && hashMatches;
            sourceArtifacts.Add(J.Obj(
                ("name", J.N(name)),
                ("sizeBytes", J.N(info.Length)),
                ("sha256", J.N(hash)),
                ("declaredByOriginalManifest", J.N(declared)),
                ("sizeMatches", J.N(sizeMatches)),
                ("sha256Matches", J.N(hashMatches))));
        }

        bool sourceDirectoryShapeMatches = expectedWithManifest.SequenceEqual(actualNames, StringComparer.OrdinalIgnoreCase);
        bool sourceHeadBound = string.Equals(sourceHead, manifestHead, StringComparison.OrdinalIgnoreCase);
        bool sourceIntegrity = sourceArtifactsMatch && sourceDirectoryShapeMatches && sourceHeadBound;

        JsonObject execution = RequiredObject(sourceScenario, "execution");
        JsonArray cleanupSteps = sourceCleanup["steps"]?.AsArray()
            ?? throw new InvalidDataException("Original live cleanup has no steps.");
        bool Step(string name, bool requireSkipped = false) => cleanupSteps.Any(item =>
        {
            if (item is not JsonObject step || !string.Equals(step["name"]?.GetValue<string>(), name, StringComparison.Ordinal))
            {
                return false;
            }

            bool ok = step["ok"]?.GetValue<bool>() ?? false;
            bool skipped = step["skipped"]?.GetValue<bool>() ?? false;
            return ok && (!requireSkipped || skipped);
        });

        bool validHardwareTakeover = string.Equals(sourcePhysicalMove["kind"]?.GetValue<string>(), "MouseMove", StringComparison.Ordinal) &&
                                     string.Equals(sourcePhysicalMove["origin"]?.GetValue<string>() ?? sourcePhysicalMove["classification"]?.GetValue<string>(), "Hardware", StringComparison.Ordinal) &&
                                     (sourcePhysicalMove["nativeFlags"]?.GetValue<uint>() ?? uint.MaxValue) == 0 &&
                                     (sourceScenario["userTakeover"]?.GetValue<bool>() ?? false) &&
                                     (sourceCleanup["userTakeover"]?.GetValue<bool>() ?? false);
        bool cancelBeforePrepare = sourceScenario["cancelBeforePrepare"]?.GetValue<bool>() ?? false;
        bool noGuardCursorSet = (sourceScenario["cursorSetCalls"]?.GetValue<long>() ?? -1) == 0 &&
                                !(sourceScenario["guardCursorRestoreAttempted"]?.GetValue<bool>() ?? true);
        bool noHarnessCursorSet = (sourceScenario["harnessCleanupCursorSetCalls"]?.GetValue<long>() ?? -1) == 0 &&
                                  !(sourceScenario["harnessCursorRestored"]?.GetValue<bool>() ?? true);
        bool noRawSend = (sourceScenario["rawCalls"]?.GetValue<long>() ?? -1) == 0 &&
                         !(sourceScenario["rawBackendReached"]?.GetValue<bool>() ?? true);
        bool executionExited = execution["threadExited"]?.GetValue<bool>() ?? false;
        bool foregroundRestoreSkipped = Step("foreground_preserve_user", requireSkipped: true) &&
                                        !Step("foreground_restore_original");
        bool threadCleanupPassed = string.Equals(sourceCleanup["status"]?.GetValue<string>(), "PASS", StringComparison.Ordinal) &&
                                    Step("observer_stop") &&
                                    Step("window_shutdown_and_wait") &&
                                    Step("sync_dispose");
        bool programDidNotInterfere = sourceIntegrity &&
                                      validHardwareTakeover &&
                                      cancelBeforePrepare &&
                                      executionExited &&
                                      noGuardCursorSet &&
                                      noHarnessCursorSet &&
                                      noRawSend &&
                                      foregroundRestoreSkipped &&
                                      threadCleanupPassed;

        string correctedStatus = programDidNotInterfere ? "PASS" : "FAIL";
        string correctedReason = programDidNotInterfere
            ? "L5_PROGRAM_NONINTERFERENCE_PASS"
            : "L5_PROGRAM_NONINTERFERENCE_FAILED";
        string sourceManifestHash = Sha256(sourceManifestPath);
        string rawHash = Sha256(Path.Combine(input, "live_raw.ndjson"));
        JsonObject sourceCursor = RequiredObject(sourceScenario, "cursor");
        JsonObject erratum = J.Obj(
            ("schemaVersion", J.N("v2.2b.l5.erratum.v1")),
            ("judgementVersion", J.N(OfflineReviewJudgementVersion)),
            ("reviewMode", J.N("independent-offline-review")),
            ("liveReexecuted", J.N(false)),
            ("rawReused", J.N(true)),
            ("sourceEvidenceDirectory", J.N(input)),
            ("sourceHead", J.N(sourceHead)),
            ("sourceManifestSha256", J.N(sourceManifestHash)),
            ("sourceRawSha256", J.N(rawHash)),
            ("currentVerifierHead", J.N(currentHead)),
            ("sourceOriginalStatus", J.N(sourceOriginalStatus)),
            ("sourceOriginalReason", J.N(sourceOriginalReason)),
            ("correctedStatus", J.N(correctedStatus)),
            ("correctedReason", J.N(correctedReason)),
            ("sourceStatusReasonInconsistencyCorrected", J.N(sourceOriginalStatus == "FAIL" && sourceOriginalReason == "OK")),
            ("coordinateEqualityNotUsed", J.N(true)),
            ("sourceCoordinateObservations", J.Obj(
                ("physicalMouseMove", sourcePhysicalMove.DeepClone()),
                ("legacyCursorSnapshot", sourceCursor["final"]?.DeepClone()),
                ("legacyCursorSnapshotInterpretation", J.N("observation-only; not used as final user position and not used for PASS")))),
            ("sourceIntegrity", J.Obj(
                ("manifestHeadMatchesSummaryHead", J.N(sourceHeadBound)),
                ("directoryShapeMatchesOriginalManifest", J.N(sourceDirectoryShapeMatches)),
                ("artifactsMatchOriginalManifest", J.N(sourceArtifactsMatch)),
                ("artifacts", sourceArtifacts))),
            ("checks", J.Obj(
                ("validHardwareTakeover", J.N(validHardwareTakeover)),
                ("cancelBeforePrepare", J.N(cancelBeforePrepare)),
                ("executionThreadExited", J.N(executionExited)),
                ("noGuardCursorSet", J.N(noGuardCursorSet)),
                ("noHarnessCleanupCursorSet", J.N(noHarnessCursorSet)),
                ("noRawSend", J.N(noRawSend)),
                ("foregroundRestoreSkipped", J.N(foregroundRestoreSkipped)),
                ("threadCleanupPassed", J.N(threadCleanupPassed)),
                ("programDidNotInterfereWithUserPosition", J.N(programDidNotInterfere)))),
            ("sourceFiles", new JsonArray(sourceNames.Select(name => (JsonNode?)J.N(name)).ToArray())));

        Directory.CreateDirectory(output);
        string reportPath = Path.Combine(output, "l5_erratum.json");
        string markdownPath = Path.Combine(output, "l5_erratum.md");
        string manifestPath = Path.Combine(output, "l5_erratum_manifest.json");
        WriteJson(reportPath, erratum);
        var markdown = new StringBuilder();
        markdown.AppendLine("# V2-2B L5 diagnostic erratum");
        markdown.AppendLine();
        markdown.AppendLine("- Review type: independent offline review; no live re-execution was performed.");
        markdown.AppendLine($"- Original evidence head: `{sourceHead}`");
        markdown.AppendLine($"- Current verifier head: `{currentHead}`");
        markdown.AppendLine($"- Original result: **{sourceOriginalStatus}**, reason `{sourceOriginalReason}`.");
        markdown.AppendLine($"- Corrected disposition under `{OfflineReviewJudgementVersion}`: **{correctedStatus}**, `{correctedReason}`.");
        markdown.AppendLine("- The original FAIL files remain unchanged; the legacy cursor coordinate comparison is not used for the corrected decision.");
        markdown.AppendLine();
        markdown.AppendLine("## Corrected acceptance checks");
        markdown.AppendLine();
        markdown.AppendLine("| Check | Result |");
        markdown.AppendLine("| --- | --- |");
        markdown.AppendLine($"| valid hardware takeover | {validHardwareTakeover} |");
        markdown.AppendLine($"| cancellation before prepare | {cancelBeforePrepare} |");
        markdown.AppendLine($"| no B cursor Set | {noGuardCursorSet} |");
        markdown.AppendLine($"| no harness cleanup cursor Set | {noHarnessCursorSet} |");
        markdown.AppendLine($"| no raw send | {noRawSend} |");
        markdown.AppendLine($"| foreground restore skipped | {foregroundRestoreSkipped} |");
        markdown.AppendLine($"| execution and cleanup threads complete | {executionExited && threadCleanupPassed} |");
        markdown.AppendLine($"| program did not interfere with user position | {programDidNotInterfere} |");
        markdown.AppendLine();
        markdown.AppendLine("Coordinates are retained as timestamped observations where the original raw contains them; no observation is treated as a required final user position.");
        File.WriteAllText(markdownPath, markdown.ToString(), new UTF8Encoding(false));

        string[] expectedOutputs = { "l5_erratum.json", "l5_erratum.md" };
        var declaredOutputs = new JsonArray();
        foreach (string name in expectedOutputs)
        {
            string path = Path.Combine(output, name);
            var info = new FileInfo(path);
            declaredOutputs.Add(J.Obj(
                ("name", J.N(name)),
                ("sizeBytes", J.N(info.Length)),
                ("sha256", J.N(Sha256(path)))));
        }

        string[] actualOutputs = Directory.GetFiles(output, "*", SearchOption.TopDirectoryOnly)
            .Where(path => !string.Equals(path, manifestPath, StringComparison.OrdinalIgnoreCase))
            .Select(Path.GetFileName)
            .Where(name => name is not null)
            .Cast<string>()
            .OrderBy(name => name, StringComparer.OrdinalIgnoreCase)
            .ToArray();
        string[] missingOutputs = expectedOutputs.Except(actualOutputs, StringComparer.OrdinalIgnoreCase).ToArray();
        string[] unexpectedOutputs = actualOutputs.Except(expectedOutputs, StringComparer.OrdinalIgnoreCase).ToArray();
        WriteJson(manifestPath, J.Obj(
            ("schemaVersion", J.N("v2.2b.erratum.manifest.v1")),
            ("mode", J.N("independent-offline-review")),
            ("judgementVersion", J.N(OfflineReviewJudgementVersion)),
            ("repository", J.N(repoRoot)),
            ("branch", J.N(GitValue(repoRoot, "rev-parse", "--abbrev-ref", "HEAD"))),
            ("sourceEvidenceDirectory", J.N(input)),
            ("sourceHead", J.N(sourceHead)),
            ("currentVerifierHead", J.N(currentHead)),
            ("sourceManifestSha256", J.N(sourceManifestHash)),
            ("sourceRawSha256", J.N(rawHash)),
            ("liveReexecuted", J.N(false)),
            ("rawReused", J.N(true)),
            ("correctedStatus", J.N(correctedStatus)),
            ("correctedReason", J.N(correctedReason)),
            ("expectedArtifacts", new JsonArray(expectedOutputs.Select(name => (JsonNode?)J.N(name)).ToArray())),
            ("declaredArtifacts", declaredOutputs),
            ("missingArtifacts", new JsonArray(missingOutputs.Select(name => (JsonNode?)J.N(name)).ToArray())),
            ("unexpectedArtifacts", new JsonArray(unexpectedOutputs.Select(name => (JsonNode?)J.N(name)).ToArray())),
            ("verifierExitCode", J.N(programDidNotInterfere && missingOutputs.Length == 0 && unexpectedOutputs.Length == 0 ? 0 : 1))));

        bool outputComplete = missingOutputs.Length == 0 && unexpectedOutputs.Length == 0;
        Console.WriteLine($"V2-2B L5 OFFLINE REVIEW {(programDidNotInterfere && outputComplete ? "PASS" : "FAIL")}: source={sourceHead}; liveReexecuted=false");
        Console.WriteLine($"Erratum: {reportPath}");
        return programDidNotInterfere && outputComplete ? 0 : 1;
    }

    public static int RunLive(string[] args)
    {
        if (!HasFlag(args, "--confirm-controlled-window") || !HasFlag(args, "--operator-present"))
        {
            Console.Error.WriteLine(
                "LIVE REFUSED: require --live --confirm-controlled-window --operator-present; no window, hook, cursor or raw backend was started.");
            return 2;
        }

        string repoRoot = FindRepositoryRoot();
        string output = Path.GetFullPath(ParseOutputDirectory(args, "build/v2-2b-live/evidence"), repoRoot);
        EnsureOutputDirectoryIsEmpty(output);
        int manualTimeoutMs = ParseInt(args, "--manual-timeout-ms", DefaultManualTimeoutMs);
        bool l1Only = HasFlag(args, "--l1-only");
        bool throughL2 = HasFlag(args, "--through-l2");
        bool l5Only = HasFlag(args, "--l5-only");
        if ((l1Only && throughL2) || (l1Only && l5Only) || (throughL2 && l5Only))
        {
            Console.Error.WriteLine("LIVE REFUSED: --l1-only, --through-l2 and --l5-only are mutually exclusive; no live activity was started.");
            return 2;
        }

        Console.WriteLine("LIVE START: controlled dummy window only; no production target and no A/B bridge.");
        Console.WriteLine($"Input budget: at most {MaxSuccessfulRawCalls} successful raw calls (L2/L3/L4 = 1 each); failure stops.");
        if (l1Only)
        {
            Console.WriteLine("Scenario plan: L1 only; later scenarios will not start in this run.");
        }
        else if (throughL2)
        {
            Console.WriteLine("Scenario plan: L1-L2 only; L3-L5 will not start; L2 cleanup then normal stop.");
        }
        else if (l5Only)
        {
            Console.WriteLine("Scenario plan: L5 diagnostic only; L1-L4 will not start; raw budget is 0.");
        }

        var results = new List<LiveScenarioResult>();
        var eventRecorder = new LiveEventRecorder();
        long successfulRawCalls = 0;
        string[] scenarios = l1Only
            ? new[] { "L1" }
            : throughL2
                ? new[] { "L1", "L2" }
                : l5Only
                    ? new[] { "L5" }
            : new[] { "L1", "L2", "L3", "L4", "L5" };
        foreach (string scenario in scenarios)
        {
            LiveScenarioResult result = RunLiveScenario(scenario, manualTimeoutMs, eventRecorder);
            results.Add(result);
            successfulRawCalls += result.RawCalls;
            if (!result.Passed || successfulRawCalls > MaxSuccessfulRawCalls)
            {
                break;
            }
        }

        bool allPassed = results.Count == scenarios.Length && results.All(result => result.Passed) &&
                         successfulRawCalls <= MaxSuccessfulRawCalls;
        WriteLiveEvidence(repoRoot, output, results, eventRecorder, successfulRawCalls, allPassed, manualTimeoutMs, l1Only, throughL2, l5Only);
        string resultLabel = !allPassed
            ? "FAIL/STOP"
            : l1Only || throughL2 || l5Only
                ? "PASS-COVERAGE-LIMITED"
                : "PASS";
        Console.WriteLine($"V2-2B LIVE {resultLabel}: {results.Count}/{scenarios.Length} scenarios; raw={successfulRawCalls}");
        if (l1Only || throughL2 || l5Only)
        {
            Console.WriteLine("Coverage is intentionally partial; this run is not a complete live PASS.");
        }
        Console.WriteLine($"Evidence: {Path.Combine(output, "live_manifest.json")}");
        return allPassed ? 0 : 1;
    }

    private static CleanupReceipt RunFakeCleanup(FakeCleanupState fake, string description)
    {
        CleanupReceipt receipt = CleanupCoordinator.Run(
            "fake",
            description,
            new CleanupSurface
            {
                StopNewActions = fake.ReleaseGuard,
                ReadTakeover = fake.ReadTakeover,
                RestoreCursorWithoutTakeover = fake.RestoreCursorWithoutTakeover,
                PreserveUserCursor = fake.PreserveUserCursor,
                StopObserver = fake.StopObserver,
                ShutdownWindow = fake.ShutdownWindow,
                RestoreForegroundWithoutTakeover = fake.RestoreForegroundWithoutTakeover,
                PreserveUserForeground = fake.PreserveUserForeground,
                WindowThreadAlive = () => fake.ThreadAlive,
                DisposeSynchronizationIfSafe = fake.DisposeSynchronizationIfSafe,
            });

        if (!receipt.Passed)
        {
            receipt.FailureReason = !fake.CursorRestoreReturns
                ? "CURSOR_RESTORE_RETURN_FALSE"
                : !fake.CursorReadReturns
                    ? "CURRENT_CURSOR_READ_FAILED"
                    : fake.TakeoverReadThrows
                        ? "TAKEOVER_STATE_READ_FAILED"
                    : !fake.WindowExitReturns
                        ? "WINDOW_THREAD_EXIT_TIMEOUT"
                        : receipt.FailureReason;
        }

        return receipt;
    }

    /// <summary>
    /// Runs the same barrier-based L5 helper used by live mode, but injects the
    /// observer, cursor and raw backends.  This is not a success stub: the fake
    /// event is emitted from an independent thread at the real pre-prepare
    /// barrier, and the resulting guard outcome is checked before cleanup.
    /// </summary>
    private static CleanupCaseResult RunFakeManualL5Case()
    {
        const long targetId = Fixture.TargetId;
        var result = new CleanupCaseResult(
            "CL10",
            "injectable L5 runner requires hardware mouse move and preserves its position");
        var eventRecorder = new LiveEventRecorder();
        var observer = new FakeInputObserver();
        var focus = new FakeFocusSnapshotProvider();
        focus.SetTarget(targetId);
        focus.SetForeground(targetId);
        var cursor = new FakeCursorBackend(10, 10);
        var raw = new CountingRawInputBackend();
        var trace = new BarrierTraceSink(
            TracePhase.Precheck1Pass,
            TimeSpan.FromSeconds(2),
            eventRecorder,
            "L5-fake");
        var guard = new InputSafetyGuard(
            observer,
            focus,
            cursor,
            raw,
            trace,
            new InputSafetyOptions
            {
                MarkerFactory = () => 0x100000F5UL,
                RestoreCursorOnCleanRelease = true,
            });
        trace.SetTimeoutCancellation(() => guard.Cancel("BARRIER_TIMEOUT"));
        var takeover = new LiveTakeoverRecorder(() => guard.Ledger.Marker);
        ObserverStartOutcome fakeStart = observer.Start(evt =>
        {
            eventRecorder.RecordObserved("L5-fake", evt);
            takeover.Record(evt);
            guard.OnObservedInput(evt);
        });

        ArmOutcome arm = guard.Arm(new ArmRequest(targetId));
        result.Check(arm.Ok, "fake L5 arm succeeds");

        using var eventDone = new ManualResetEventSlim(false);
        using var promptReady = new ManualResetEventSlim(false);
        var eventThread = new Thread(() =>
        {
            if (!trace.Reached.Wait(TimeSpan.FromSeconds(1)))
            {
                eventDone.Set();
                return;
            }

            if (!promptReady.Wait(TimeSpan.FromSeconds(1)))
            {
                eventDone.Set();
                return;
            }

            cursor.ForcePosition(99, 99);
            ObservedInputEvent physicalMove = observer.Next(
                InputEventKind.MouseMove,
                InputEventOrigin.Hardware,
                0,
                99,
                99);
            observer.Emit(physicalMove);
            eventDone.Set();
        })
        {
            IsBackground = true,
            Name = "v2-2b-fake-l5-physical-move",
        };
        eventThread.Start();

        var liveResult = new LiveScenarioResult("L5-fake", "injectable L5")
        {
            WindowCreated = false,
            ForegroundAcquired = false,
            HookStarted = false,
            ObserverStartReason = fakeStart.Reason,
        };
        RunManualTakeover(
            liveResult,
            guard,
            raw,
            cursor,
            trace,
            takeover,
            eventRecorder,
            1000,
            observer,
            null,
            () => promptReady.Set());
        bool eventThreadExited = eventThread.Join(TimeSpan.FromSeconds(1)) && eventDone.IsSet;

        bool cursorRestoreCalled = false;
        bool foregroundRestoreCalled = false;
        CleanupReceipt receipt = CleanupCoordinator.Run(
            "L5-fake",
            "injectable L5",
            new CleanupSurface
            {
                StopNewActions = () =>
                {
                    ReleaseOutcome release = guard.Release();
                    return release.Ok
                        ? CleanupActionResult.Success(release.Reason)
                        : CleanupActionResult.Failure(release.Reason);
                },
                ReadTakeover = takeover.Read,
                RestoreCursorWithoutTakeover = () =>
                {
                    cursorRestoreCalled = true;
                    return CleanupActionResult.Failure("UNEXPECTED_CURSOR_RESTORE");
                },
                PreserveUserCursor = () =>
                {
                    (int X, int Y) position = cursor.GetPosition();
                    return takeover.Read().Seen && position == (99, 99) && cursor.SetCallCount == 0
                        ? CleanupActionResult.Skip("CURSOR_RESTORE_USER_TAKEOVER")
                        : CleanupActionResult.Failure("FAKE_USER_CURSOR_NOT_PRESERVED");
                },
                StopObserver = () =>
                {
                    observer.Stop();
                    return CleanupActionResult.Success("FAKE_OBSERVER_STOPPED");
                },
                ShutdownWindow = () => CleanupActionResult.Success("FAKE_WINDOW_EXITED"),
                RestoreForegroundWithoutTakeover = () =>
                {
                    foregroundRestoreCalled = true;
                    return CleanupActionResult.Failure("UNEXPECTED_FOREGROUND_RESTORE");
                },
                PreserveUserForeground = () => CleanupActionResult.Skip("FOREGROUND_RESTORE_USER_TAKEOVER"),
                WindowThreadAlive = () => false,
                DisposeSynchronizationIfSafe = () => CleanupActionResult.Success("FAKE_SYNC_DISPOSED"),
            });

        liveResult.Cleanup = receipt;
        liveResult.UserTakeover = receipt.UserTakeover;
        liveResult.GuardCursorRestoreAttempted = false;
        liveResult.HarnessCleanupCursorSetCalls = 0;
        liveResult.HarnessCursorRestored = false;
        liveResult.ObserverAfterCleanup = observer.Diagnostics();
        (int X, int Y) cleanupCursorObservation = cursor.GetPosition();
        liveResult.CursorAfterCleanupObservation = J.Obj(
            ("stage", J.N("cleanup_complete_read")),
            ("x", J.N(cleanupCursorObservation.X)),
            ("y", J.N(cleanupCursorObservation.Y)),
            ("observedAtNs", J.N(TraceClock.NowNs())));
        liveResult.ProgramDidNotInterfereWithUserPosition =
            EvaluateL5ProgramNonInterference(liveResult, receipt);
        liveResult.UserPositionUnchanged = liveResult.ProgramDidNotInterfereWithUserPosition;
        liveResult.Passed = liveResult.Passed && receipt.Passed && eventThreadExited &&
                            liveResult.ProgramDidNotInterfereWithUserPosition;
        result.Receipt = receipt;
        result.Note = liveResult.ToJson().ToJsonString();
        result.Check(eventThreadExited, "physical event injector thread exits");
        result.Check(liveResult.PhysicalMouseMoveObserved, "L5 records an observed event");
        result.Check(liveResult.PhysicalMouseMove is { Kind: InputEventKind.MouseMove, Origin: InputEventOrigin.Hardware },
            "L5 sample is MouseMove + Hardware");
        result.Check(fakeStart.Ok && liveResult.L5BarrierReady, "L5 records observer start and barrier readiness");
        result.Check(liveResult.L5PromptDisplayed &&
                     liveResult.L5PromptNs > liveResult.L5BarrierReadyNs &&
                     liveResult.L5ManualWaitStartedNs >= liveResult.L5PromptNs,
            "L5 starts the manual wait only after the prompt");
        result.Check(liveResult.PhysicalMouseMove is { NativeFlags: 0 } &&
                     liveResult.L5MouseEvents.Count == 1 &&
                     liveResult.ObserverAfterWait is { ForwardedEvents: 1, SinkFaults: 0, ClassificationFaults: 0 },
            "L5 records one classified mouse event with zero observer faults");
        result.Check(liveResult.CancelBeforePrepare, "hardware move cancels before prepare");
        result.Check(liveResult.CursorSetCalls == 0, "cancel before prepare makes zero cursor Set calls");
        result.Check(liveResult.RawCalls == 0, "cancel before prepare makes zero raw Send calls");
        result.Check(liveResult.ExecutionThreadExited && !liveResult.ExecutionOutcomeOk,
            "execution thread returns a failed outcome without exception");
        result.Check(receipt.Passed && receipt.UserTakeover, "cleanup preserves the takeover branch");
        result.Check(!cursorRestoreCalled && !foregroundRestoreCalled,
            "takeover cleanup does not restore cursor or foreground");
        result.Check(cursor.SetCallCount == 0 && liveResult.ProgramDidNotInterfereWithUserPosition,
            "program does not overwrite the user cursor position");
        return result;
    }

    private static CleanupCaseResult RunFakeManualL5MovingDuringCleanupCase()
    {
        const long targetId = Fixture.TargetId;
        var result = new CleanupCaseResult(
            "CL11",
            "multiple hardware moves during cleanup preserve user position");
        var eventRecorder = new LiveEventRecorder();
        var observer = new FakeInputObserver();
        var focus = new FakeFocusSnapshotProvider();
        focus.SetTarget(targetId);
        focus.SetForeground(targetId);
        var cursor = new FakeCursorBackend(10, 10);
        var raw = new CountingRawInputBackend();
        var trace = new BarrierTraceSink(
            TracePhase.Precheck1Pass,
            TimeSpan.FromSeconds(2),
            eventRecorder,
            "L5-moving-fake");
        var guard = new InputSafetyGuard(
            observer,
            focus,
            cursor,
            raw,
            trace,
            new InputSafetyOptions
            {
                MarkerFactory = () => 0x100000F6UL,
                RestoreCursorOnCleanRelease = true,
            });
        trace.SetTimeoutCancellation(() => guard.Cancel("BARRIER_TIMEOUT"));
        var takeover = new LiveTakeoverRecorder(() => guard.Ledger.Marker);
        ObserverStartOutcome fakeStart = observer.Start(evt =>
        {
            eventRecorder.RecordObserved("L5-moving-fake", evt);
            takeover.Record(evt);
            guard.OnObservedInput(evt);
        });

        ArmOutcome arm = guard.Arm(new ArmRequest(targetId));
        result.Check(arm.Ok, "fake moving L5 arm succeeds");

        using var eventDone = new ManualResetEventSlim(false);
        using var promptReady = new ManualResetEventSlim(false);
        using var firstMoveDone = new ManualResetEventSlim(false);
        using var cleanupMoveGate = new ManualResetEventSlim(false);
        using var cleanupMovesDone = new ManualResetEventSlim(false);
        var eventThread = new Thread(() =>
        {
            try
            {
                if (!trace.Reached.Wait(TimeSpan.FromSeconds(1)) ||
                    !promptReady.Wait(TimeSpan.FromSeconds(1)))
                {
                    return;
                }

                cursor.ForcePosition(99, 99);
                observer.Emit(observer.Next(InputEventKind.MouseMove, InputEventOrigin.Hardware, 0, 99, 99));
                firstMoveDone.Set();

                if (!cleanupMoveGate.Wait(TimeSpan.FromSeconds(2)))
                {
                    return;
                }

                cursor.ForcePosition(101, 102);
                observer.Emit(observer.Next(InputEventKind.MouseMove, InputEventOrigin.Hardware, 0, 101, 102));
                cursor.ForcePosition(103, 104);
                observer.Emit(observer.Next(InputEventKind.MouseMove, InputEventOrigin.Hardware, 0, 103, 104));
                cleanupMovesDone.Set();
            }
            finally
            {
                eventDone.Set();
            }
        })
        {
            IsBackground = true,
            Name = "v2-2b-fake-l5-moving-during-cleanup",
        };
        eventThread.Start();

        var liveResult = new LiveScenarioResult("L5-moving-fake", "injectable L5 moving during cleanup")
        {
            WindowCreated = false,
            ForegroundAcquired = false,
            HookStarted = false,
            ObserverStartReason = fakeStart.Reason,
        };
        RunManualTakeover(
            liveResult,
            guard,
            raw,
            cursor,
            trace,
            takeover,
            eventRecorder,
            1000,
            observer,
            null,
            () => promptReady.Set());
        bool firstMoveExited = firstMoveDone.Wait(TimeSpan.FromSeconds(1));

        bool cursorRestoreCalled = false;
        bool foregroundRestoreCalled = false;
        liveResult.L5CleanupStartNs = TraceClock.NowNs();
        CleanupReceipt receipt = CleanupCoordinator.Run(
            "L5-moving-fake",
            "injectable L5 moving during cleanup",
            new CleanupSurface
            {
                StopNewActions = () =>
                {
                    ReleaseOutcome release = guard.Release();
                    cleanupMoveGate.Set();
                    bool movesArrived = cleanupMovesDone.Wait(TimeSpan.FromSeconds(1));
                    return release.Ok && movesArrived
                        ? CleanupActionResult.Success(release.Reason)
                        : CleanupActionResult.Failure(!release.Ok ? release.Reason : "FAKE_CLEANUP_MOVES_TIMEOUT");
                },
                ReadTakeover = takeover.Read,
                RestoreCursorWithoutTakeover = () =>
                {
                    cursorRestoreCalled = true;
                    return CleanupActionResult.Failure("UNEXPECTED_CURSOR_RESTORE");
                },
                PreserveUserCursor = () =>
                {
                    TakeoverReadResult state = takeover.Read();
                    return state.Ok && state.Seen && cursor.SetCallCount == 0
                        ? CleanupActionResult.Skip("CURSOR_RESTORE_USER_TAKEOVER")
                        : CleanupActionResult.Failure("FAKE_USER_CURSOR_NOT_PRESERVED");
                },
                StopObserver = () =>
                {
                    observer.Stop();
                    return CleanupActionResult.Success("FAKE_OBSERVER_STOPPED");
                },
                ShutdownWindow = () => CleanupActionResult.Success("FAKE_WINDOW_EXITED"),
                RestoreForegroundWithoutTakeover = () =>
                {
                    foregroundRestoreCalled = true;
                    return CleanupActionResult.Failure("UNEXPECTED_FOREGROUND_RESTORE");
                },
                PreserveUserForeground = () => CleanupActionResult.Skip("FOREGROUND_RESTORE_USER_TAKEOVER"),
                WindowThreadAlive = () => false,
                DisposeSynchronizationIfSafe = () => CleanupActionResult.Success("FAKE_SYNC_DISPOSED"),
            });
        liveResult.L5CleanupEndNs = TraceClock.NowNs();
        liveResult.ObserverAfterCleanup = observer.Diagnostics();
        foreach (ObservedInputEvent observed in takeover.SnapshotEvents()
                     .Where(observed => observed.Device == InputDeviceClass.Mouse &&
                                        observed.MonotonicNs >= liveResult.L5CleanupStartNs))
        {
            liveResult.L5MouseEventsAfterCleanup.Add(MouseEventJson(observed));
        }
        liveResult.Cleanup = receipt;
        liveResult.UserTakeover = receipt.UserTakeover;
        liveResult.GuardCursorRestoreAttempted = false;
        liveResult.HarnessCleanupCursorSetCalls = 0;
        liveResult.HarnessCursorRestored = false;
        (int X, int Y) cleanupCursorObservation = cursor.GetPosition();
        liveResult.CursorAfterCleanupObservation = J.Obj(
            ("stage", J.N("cleanup_complete_read")),
            ("x", J.N(cleanupCursorObservation.X)),
            ("y", J.N(cleanupCursorObservation.Y)),
            ("observedAtNs", J.N(TraceClock.NowNs())));
        liveResult.ProgramDidNotInterfereWithUserPosition =
            EvaluateL5ProgramNonInterference(liveResult, receipt);
        liveResult.UserPositionUnchanged = liveResult.ProgramDidNotInterfereWithUserPosition;
        liveResult.Passed = liveResult.Passed && receipt.Passed &&
                            liveResult.ProgramDidNotInterfereWithUserPosition;
        bool eventThreadExited = eventThread.Join(TimeSpan.FromSeconds(1)) && eventDone.IsSet;

        result.Receipt = receipt;
        result.Note = liveResult.ToJson().ToJsonString();
        result.Check(eventThreadExited, "continuous fake input thread exits");
        result.Check(firstMoveExited, "first hardware move arrives before cleanup");
        result.Check(liveResult.L5MouseEventsAfterCleanup.Count == 2,
            "two hardware moves arrive during cleanup after the wait snapshot");
        result.Check(liveResult.L5MouseEventsAfterCleanup.All(item =>
        {
            if (item is not JsonObject eventObject)
            {
                return false;
            }

            string? classification = eventObject["classification"]?.GetValue<string>();
            long flags = eventObject["nativeFlags"]?.GetValue<long>() ?? -1;
            return classification == "Hardware" && flags == 0;
        }), "cleanup-period moves remain classified as Hardware with zero flags");
        result.Check(fakeStart.Ok && liveResult.L5BarrierReady && liveResult.L5PromptDisplayed,
            "moving L5 records observer start, barrier readiness and prompt");
        result.Check(liveResult.CancelBeforePrepare && liveResult.ExecutionThreadExited,
            "takeover cancels before prepare and the execution thread exits");
        result.Check(liveResult.CursorSetCalls == 0 && cursor.SetCallCount == 0,
            "no B or cleanup cursor Set call occurs while the user keeps moving");
        result.Check(liveResult.RawCalls == 0, "moving takeover sends no raw input");
        result.Check(receipt.Passed && receipt.UserTakeover && !cursorRestoreCalled && !foregroundRestoreCalled,
            "cleanup preserves the user takeover branch");
        result.Check(liveResult.ObserverAfterCleanup is { IsRunning: false, ThreadAlive: false, ForwardedEvents: 3 },
            "observer cleanup snapshot records all three mouse events and stopped state");
        result.Check(liveResult.ProgramDidNotInterfereWithUserPosition,
            "program does not interfere with the user position during cleanup");
        result.Check(cursor.GetPosition() == (103, 104),
            "cleanup cursor observation records the last fake user sample without calling SetPosition");
        return result;
    }

    /// <summary>
    /// The barrier is the only thing holding the execution thread before
    /// prepare.  With no Continue signal and no observed input, its timeout must
    /// cancel the guard itself; it must not be possible to fall through to a
    /// cursor move or raw call.
    /// </summary>
    private static CleanupCaseResult RunFakeBarrierTimeoutCase()
    {
        const long targetId = Fixture.TargetId;
        var result = new CleanupCaseResult(
            "BF01",
            "barrier timeout cancels before prepare with no input event");
        var eventRecorder = new LiveEventRecorder();
        var observer = new FakeInputObserver();
        var focus = new FakeFocusSnapshotProvider();
        focus.SetTarget(targetId);
        focus.SetForeground(targetId);
        var cursor = new FakeCursorBackend(10, 10);
        var raw = new CountingRawInputBackend();
        var trace = new BarrierTraceSink(
            TracePhase.Precheck1Pass,
            TimeSpan.FromMilliseconds(75),
            eventRecorder,
            "BF01-fake");
        var guard = new InputSafetyGuard(
            observer,
            focus,
            cursor,
            raw,
            trace,
            new InputSafetyOptions
            {
                MarkerFactory = () => 0x100000B1UL,
                RestoreCursorOnCleanRelease = true,
            });
        trace.SetTimeoutCancellation(() => guard.Cancel("BARRIER_TIMEOUT"));
        var takeover = new LiveTakeoverRecorder(() => guard.Ledger.Marker);
        observer.Start(evt =>
        {
            eventRecorder.RecordObserved("BF01-fake", evt);
            takeover.Record(evt);
            guard.OnObservedInput(evt);
        });

        ArmOutcome arm = guard.Arm(new ArmRequest(targetId));
        var liveResult = new LiveScenarioResult("BF01-fake", "barrier timeout")
        {
            WindowCreated = false,
            ForegroundAcquired = false,
            HookStarted = false,
        };
        RunManualTakeover(liveResult, guard, raw, cursor, trace, takeover, eventRecorder, 1000, observer, null);
        CleanupReceipt receipt = RunFakeBarrierCleanup("BF01-fake", guard, observer, cursor, takeover);

        liveResult.Cleanup = receipt;
        eventRecorder.RecordCleanup("BF01-fake", receipt);
        result.Receipt = receipt;
        result.Note = J.Obj(
            ("armOk", J.N(arm.Ok)),
            ("barrierWaitTimedOut", J.N(trace.WaitTimedOut)),
            ("continueSet", J.N(trace.Continue.IsSet)),
            ("inputEventCount", J.N(takeover.EventCount)),
            ("trace", new JsonArray(eventRecorder.Snapshot().Select(item => (JsonNode?)item).ToArray())),
            ("liveResult", liveResult.ToJson())).ToJsonString();
        result.Check(arm.Ok, "fake barrier timeout arm succeeds");
        result.Check(trace.WaitTimedOut, "barrier records its own timeout");
        result.Check(takeover.EventCount == 0, "timeout case has no input event");
        result.Check(!liveResult.Passed, "no valid manual sample cannot pass");
        result.Check(liveResult.ExecutionThreadExited, "execution thread exits after barrier timeout");
        result.Check(liveResult.CancelBeforePrepare, "timeout cancellation is visible before prepare");
        result.Check(!liveResult.ExecutionOutcomeOk && liveResult.ExecutionException.Length == 0,
            "timeout produces a failed execution outcome without an exception");
        result.Check(liveResult.CursorSetCalls == 0, "barrier timeout makes zero cursor Set calls");
        result.Check(liveResult.RawCalls == 0, "barrier timeout makes zero raw Send calls");
        result.Check(!trace.Inner.Contains(TracePhase.CursorPrepareInvoked),
            "barrier timeout emits no cursor prepare trace");
        result.Check(receipt.Passed, "timeout cleanup completes after the execution thread exits");
        return result;
    }

    /// <summary>
    /// The delayed thread is held behind a second deterministic gate.  The
    /// action is allowed to observe the barrier timeout and exit first; only then
    /// is the late hardware event released.  This proves safety does not depend
    /// on which thread happens to win a timeout race.
    /// </summary>
    private static CleanupCaseResult RunFakeBarrierDelayedInputCase()
    {
        const long targetId = Fixture.TargetId;
        var result = new CleanupCaseResult(
            "BF02",
            "late observer thread cannot reopen a timed-out barrier");
        var eventRecorder = new LiveEventRecorder();
        var observer = new FakeInputObserver();
        var focus = new FakeFocusSnapshotProvider();
        focus.SetTarget(targetId);
        focus.SetForeground(targetId);
        var cursor = new FakeCursorBackend(10, 10);
        var raw = new CountingRawInputBackend();
        var trace = new BarrierTraceSink(
            TracePhase.Precheck1Pass,
            TimeSpan.FromMilliseconds(75),
            eventRecorder,
            "BF02-fake");
        var guard = new InputSafetyGuard(
            observer,
            focus,
            cursor,
            raw,
            trace,
            new InputSafetyOptions
            {
                MarkerFactory = () => 0x100000B2UL,
                RestoreCursorOnCleanRelease = true,
            });
        trace.SetTimeoutCancellation(() => guard.Cancel("BARRIER_TIMEOUT"));
        var takeover = new LiveTakeoverRecorder(() => guard.Ledger.Marker);
        observer.Start(evt =>
        {
            eventRecorder.RecordObserved("BF02-fake", evt);
            takeover.Record(evt);
            guard.OnObservedInput(evt);
        });

        ArmOutcome arm = guard.Arm(new ArmRequest(targetId));
        using var delayedReady = new ManualResetEventSlim(false);
        using var releaseDelayedInput = new ManualResetEventSlim(false);
        using var delayedDone = new ManualResetEventSlim(false);
        var delayedThread = new Thread(() =>
        {
            try
            {
                if (!trace.Reached.Wait(TimeSpan.FromSeconds(1)))
                {
                    return;
                }

                delayedReady.Set();
                if (!releaseDelayedInput.Wait(TimeSpan.FromSeconds(2)))
                {
                    return;
                }

                cursor.ForcePosition(99, 99);
                observer.Emit(observer.Next(
                    InputEventKind.MouseMove,
                    InputEventOrigin.Hardware,
                    0,
                    99,
                    99));
            }
            finally
            {
                delayedDone.Set();
            }
        })
        {
            IsBackground = true,
            Name = "v2-2b-fake-barrier-delayed-input",
        };
        delayedThread.Start();

        var liveResult = new LiveScenarioResult("BF02-fake", "delayed input after barrier timeout")
        {
            WindowCreated = false,
            ForegroundAcquired = false,
            HookStarted = false,
        };
        RunManualTakeover(liveResult, guard, raw, cursor, trace, takeover, eventRecorder, 1000, observer, null);
        bool actionSafeBeforeLateInput = liveResult.ExecutionThreadExited &&
            liveResult.CursorSetCalls == 0 && liveResult.RawCalls == 0;
        bool delayedWasReady = delayedReady.Wait(TimeSpan.FromSeconds(1));
        releaseDelayedInput.Set();
        bool delayedThreadExited = delayedThread.Join(TimeSpan.FromSeconds(1)) && delayedDone.IsSet;
        bool lateEventRecorded = takeover.FirstHardwareMouseMove is
            { Kind: InputEventKind.MouseMove, Origin: InputEventOrigin.Hardware };

        CleanupReceipt receipt = RunFakeBarrierCleanup("BF02-fake", guard, observer, cursor, takeover);

        liveResult.Cleanup = receipt;
        eventRecorder.RecordCleanup("BF02-fake", receipt);
        result.Receipt = receipt;
        result.Note = J.Obj(
            ("armOk", J.N(arm.Ok)),
            ("barrierWaitTimedOut", J.N(trace.WaitTimedOut)),
            ("delayedThreadWasReady", J.N(delayedWasReady)),
            ("delayedThreadExited", J.N(delayedThreadExited)),
            ("lateEventRecorded", J.N(lateEventRecorded)),
            ("userPositionAfterLateEvent", J.Obj(("x", J.N(cursor.GetPosition().X)), ("y", J.N(cursor.GetPosition().Y)))),
            ("trace", new JsonArray(eventRecorder.Snapshot().Select(item => (JsonNode?)item).ToArray())),
            ("liveResult", liveResult.ToJson())).ToJsonString();
        result.Check(arm.Ok, "fake delayed barrier arm succeeds");
        result.Check(trace.WaitTimedOut, "barrier times out before the delayed event is released");
        result.Check(delayedWasReady, "delayed input thread reaches its hold gate");
        result.Check(actionSafeBeforeLateInput, "execution exits with zero cursor and raw deltas before late input");
        result.Check(!liveResult.Passed, "late input cannot turn the timed-out run into a PASS");
        result.Check(liveResult.CancelBeforePrepare, "timeout cancellation remains before prepare");
        result.Check(delayedThreadExited && lateEventRecorded, "late hardware event is recorded after execution exit");
        result.Check(liveResult.CursorSetCalls == 0 && liveResult.RawCalls == 0,
            "late input does not add cursor or raw execution calls");
        result.Check(cursor.GetPosition() == (99, 99), "late user position is preserved");
        result.Check(receipt.Passed && receipt.UserTakeover, "cleanup preserves the late takeover branch");
        result.Check(!trace.Inner.Contains(TracePhase.CursorPrepareInvoked),
            "late input cannot reopen cursor prepare");
        return result;
    }

    private static CleanupReceipt RunFakeBarrierCleanup(
        string scenario,
        InputSafetyGuard guard,
        FakeInputObserver observer,
        FakeCursorBackend cursor,
        LiveTakeoverRecorder takeover)
    {
        return CleanupCoordinator.Run(
            scenario,
            "barrier timeout fake cleanup",
            new CleanupSurface
            {
                StopNewActions = () =>
                {
                    ReleaseOutcome release = guard.Release();
                    return release.Ok
                        ? CleanupActionResult.Success(release.Reason)
                        : CleanupActionResult.Failure(release.Reason);
                },
                ReadTakeover = takeover.Read,
                RestoreCursorWithoutTakeover = () =>
                {
                    (int X, int Y) position = cursor.GetPosition();
                    return position == (10, 10) && cursor.SetCallCount == 0
                        ? CleanupActionResult.Success("NO_CURSOR_OPERATION_REQUIRED")
                        : CleanupActionResult.Failure("UNEXPECTED_CURSOR_SIDE_EFFECT");
                },
                PreserveUserCursor = () =>
                {
                    TakeoverReadResult state = takeover.Read();
                    (int X, int Y) position = cursor.GetPosition();
                    return state.Seen && position == (99, 99) && cursor.SetCallCount == 0
                        ? CleanupActionResult.Skip("CURSOR_RESTORE_USER_TAKEOVER")
                        : CleanupActionResult.Failure("LATE_USER_CURSOR_NOT_PRESERVED");
                },
                StopObserver = () =>
                {
                    observer.Stop();
                    return CleanupActionResult.Success("FAKE_OBSERVER_STOPPED");
                },
                ShutdownWindow = () => CleanupActionResult.Success("FAKE_WINDOW_EXITED"),
                RestoreForegroundWithoutTakeover = () => CleanupActionResult.Success("FAKE_FOREGROUND_RESTORED"),
                PreserveUserForeground = () => CleanupActionResult.Skip("FOREGROUND_RESTORE_USER_TAKEOVER"),
                WindowThreadAlive = () => false,
                DisposeSynchronizationIfSafe = () => CleanupActionResult.Success("FAKE_SYNC_DISPOSED"),
            });
    }

    private static CleanupCaseResult RunFakeForegroundRequestRejectedCase()
    {
        var result = new CleanupCaseResult(
            "FG01",
            "foreground request rejection is diagnosed without confirmation");
        var fake = new FakeForegroundRestoreSurface { SetForegroundReturns = false };
        ForegroundRestoreResult restore = RunFakeForegroundRestore(
            fake,
            () => TakeoverReadResult.Success(false, "FAKE_NO_TAKEOVER"));
        result.Note = ForegroundRestoreToJson(restore).ToJsonString();
        result.Check(!restore.Ok, "request rejection is not a restore success");
        result.Check(restore.Reason == "FOREGROUND_REQUEST_REJECTED",
            "request rejection has its own reason");
        result.Check(restore.SetForegroundCalled && !restore.SetForegroundReturned,
            "SetForegroundWindow call and false return are recorded");
        result.Check(restore.ActualBefore == fake.OtherWindow && restore.ActualAfter == fake.OtherWindow,
            "actual foreground is recorded before and after the rejected request");
        result.Check(restore.TakeoverReadCount == 0, "rejected request does not enter confirmation polling");
        return result;
    }

    private static CleanupCaseResult RunFakeForegroundConfirmationTimeoutCase()
    {
        var result = new CleanupCaseResult(
            "FG02",
            "foreground confirmation timeout is bounded and diagnosed");
        var fake = new FakeForegroundRestoreSurface();
        ForegroundRestoreResult restore = RunFakeForegroundRestore(
            fake,
            () => TakeoverReadResult.Success(false, "FAKE_NO_TAKEOVER"),
            TimeSpan.FromMilliseconds(25));
        result.Note = ForegroundRestoreToJson(restore).ToJsonString();
        result.Check(!restore.Ok, "confirmation timeout is not a restore success");
        result.Check(restore.Reason == "FOREGROUND_CONFIRMATION_TIMEOUT",
            "confirmation timeout has its own reason");
        result.Check(restore.SetForegroundCalled && restore.SetForegroundReturned,
            "request was accepted before confirmation timed out");
        result.Check(restore.PollCount > 0 && restore.TakeoverReadCount > 0,
            "timeout path performs bounded confirmation polling");
        result.Check(fake.SetForegroundCalls == 1, "timeout path does not repeat focus requests");
        result.Check(restore.ElapsedMs <= 25, "fake clock proves timeout stays within the bound");
        return result;
    }

    private static CleanupCaseResult RunFakeOriginalForegroundInvalidCase()
    {
        var result = new CleanupCaseResult(
            "FG03",
            "invalid original foreground is diagnosed before request");
        var fake = new FakeForegroundRestoreSurface { OriginalWindowValid = false };
        ForegroundRestoreResult restore = RunFakeForegroundRestore(
            fake,
            () => TakeoverReadResult.Success(false, "FAKE_NO_TAKEOVER"));
        result.Note = ForegroundRestoreToJson(restore).ToJsonString();
        result.Check(!restore.Ok, "invalid original window is not a restore success");
        result.Check(restore.Reason == "ORIGINAL_FOREGROUND_INVALID",
            "invalid original window has its own reason");
        result.Check(!restore.OriginalWindowValid && !restore.SetForegroundCalled,
            "invalid original window prevents SetForegroundWindow");
        result.Check(restore.ActualBefore == fake.OtherWindow &&
                     restore.ActualAfterStatus == ForegroundWindowReadStatus.NotRead &&
                     !restore.ActualAfterRead,
            "invalid-original path records actual-before and does not invent actual-after");
        return result;
    }

    private static CleanupCaseResult RunFakeForegroundDelayedSuccessCase()
    {
        var result = new CleanupCaseResult(
            "FG04",
            "foreground confirmation waits for delayed success");
        var fake = new FakeForegroundRestoreSurface { ConfirmAfterReads = 2 };
        ForegroundRestoreResult restore = RunFakeForegroundRestore(
            fake,
            () => TakeoverReadResult.Success(false, "FAKE_NO_TAKEOVER"));
        result.Note = ForegroundRestoreToJson(restore).ToJsonString();
        result.Check(restore.Ok && restore.Reason == "FOREGROUND_RESTORE_OK",
            "delayed confirmation eventually restores foreground");
        result.Check(restore.SetForegroundCalled && restore.SetForegroundReturned,
            "successful request return is recorded");
        result.Check(restore.ActualAfter == fake.OriginalWindow && restore.ActualAfterRead,
            "success is based on confirmed actual foreground");
        result.Check(restore.PollCount >= 2 && restore.TakeoverReadCount >= 3,
            "success follows multiple bounded confirmation samples");
        result.Check(fake.SetForegroundCalls == 1, "delayed success does not repeat focus requests");
        return result;
    }

    private static CleanupCaseResult RunFakeForegroundTakeoverCase()
    {
        var result = new CleanupCaseResult(
            "FG05",
            "takeover during foreground confirmation stops recovery");
        var fake = new FakeForegroundRestoreSurface();
        int readCount = 0;
        ForegroundRestoreResult restore = RunFakeForegroundRestore(
            fake,
            () => ++readCount >= 2
                ? TakeoverReadResult.Success(true, "FAKE_USER_TAKEOVER")
                : TakeoverReadResult.Success(false, "FAKE_NO_TAKEOVER"));
        result.Note = ForegroundRestoreToJson(restore).ToJsonString();
        result.Check(!restore.Ok && restore.Skipped && restore.UserTakeover,
            "takeover is a terminal preserve decision");
        result.Check(restore.Reason == "FOREGROUND_RESTORE_USER_TAKEOVER_DURING_CONFIRMATION",
            "takeover during confirmation has its own reason");
        result.Check(restore.TakeoverReadCount == 2 && fake.SetForegroundCalls == 1,
            "takeover stops polling without another focus request");
        result.Check(restore.ActualBefore == fake.OtherWindow,
            "actual foreground before request is recorded");
        return result;
    }

    private static CleanupCaseResult RunFakeForegroundReadFailureCase()
    {
        var result = new CleanupCaseResult(
            "FG06",
            "takeover read failure during foreground confirmation stops recovery");
        var fake = new FakeForegroundRestoreSurface();
        ForegroundRestoreResult restore = RunFakeForegroundRestore(
            fake,
            () => TakeoverReadResult.Failure("FAKE_TAKEOVER_READ_FAILED"));
        result.Note = ForegroundRestoreToJson(restore).ToJsonString();
        result.Check(!restore.Ok && !restore.Skipped,
            "takeover read failure is not a preserve success");
        result.Check(restore.Reason ==
                     "TAKEOVER_STATE_READ_FAILED_DURING_FOREGROUND_RESTORE:FAKE_TAKEOVER_READ_FAILED",
            "takeover read failure has its own reason");
        result.Check(restore.TakeoverReadCount == 1 && fake.SetForegroundCalls == 1,
            "read failure stops confirmation without another focus request");
        return result;
    }

    private static CleanupCaseResult RunFakeForegroundNullThenTargetCase()
    {
        var result = new CleanupCaseResult(
            "FG07",
            "normal NULL foreground result waits for target confirmation");
        var fake = new FakeForegroundRestoreSurface
        {
            NullForegroundReads = 2,
            ConfirmAfterReads = 0,
        };
        ForegroundRestoreResult restore = RunFakeForegroundRestore(
            fake,
            () => TakeoverReadResult.Success(false, "FAKE_NO_TAKEOVER"));
        result.Note = ForegroundRestoreToJson(restore).ToJsonString();
        result.Check(restore.Ok && restore.Reason == "FOREGROUND_RESTORE_OK",
            "NULL during transition eventually confirms the target");
        result.Check(restore.NullForegroundReadCount >= 2 &&
                     restore.ActualAfterStatus == ForegroundWindowReadStatus.ValidWindow,
            "normal NULL results are counted separately from the final HWND");
        result.Check(restore.ActualAfter == fake.OriginalWindow,
            "only the confirmed target HWND makes the restore pass");
        result.Check(fake.SetForegroundCalls == 1, "NULL handling does not repeat focus requests");
        return result;
    }

    private static CleanupCaseResult RunFakeForegroundNullTimeoutCase()
    {
        var result = new CleanupCaseResult(
            "FG08",
            "continuous NULL foreground results time out");
        var fake = new FakeForegroundRestoreSurface
        {
            AlwaysReturnNullDuringConfirmation = true,
        };
        ForegroundRestoreResult restore = RunFakeForegroundRestore(
            fake,
            () => TakeoverReadResult.Success(false, "FAKE_NO_TAKEOVER"),
            TimeSpan.FromMilliseconds(25));
        result.Note = ForegroundRestoreToJson(restore).ToJsonString();
        result.Check(!restore.Ok && restore.Reason == "FOREGROUND_CONFIRMATION_TIMEOUT",
            "continuous NULL is a bounded confirmation failure");
        result.Check(restore.ActualAfterStatus == ForegroundWindowReadStatus.Null &&
                     restore.ActualAfter == IntPtr.Zero,
            "timeout records NULL as the final actual foreground result");
        result.Check(restore.NullForegroundReadCount > 0 && restore.PollCount > 0,
            "NULL count and polling are both recorded");
        result.Check(fake.SetForegroundCalls == 1, "NULL timeout does not repeat focus requests");
        return result;
    }

    private static CleanupCaseResult RunFakeForegroundNullTakeoverCase()
    {
        var result = new CleanupCaseResult(
            "FG09",
            "takeover during NULL foreground wait stops recovery");
        var fake = new FakeForegroundRestoreSurface
        {
            AlwaysReturnNullDuringConfirmation = true,
        };
        int readCount = 0;
        ForegroundRestoreResult restore = RunFakeForegroundRestore(
            fake,
            () => ++readCount >= 2
                ? TakeoverReadResult.Success(true, "FAKE_USER_TAKEOVER")
                : TakeoverReadResult.Success(false, "FAKE_NO_TAKEOVER"));
        result.Note = ForegroundRestoreToJson(restore).ToJsonString();
        result.Check(!restore.Ok && restore.Skipped && restore.UserTakeover,
            "takeover stops the NULL wait as a preserve decision");
        result.Check(restore.Reason == "FOREGROUND_RESTORE_USER_TAKEOVER_DURING_CONFIRMATION",
            "NULL-wait takeover has the takeover-specific reason");
        result.Check(restore.ActualAfterStatus == ForegroundWindowReadStatus.Null &&
                     restore.NullForegroundReadCount > 0,
            "NULL observations remain recorded on takeover stop");
        result.Check(fake.SetForegroundCalls == 1, "takeover during NULL wait does not repeat focus requests");
        return result;
    }

    private static CleanupCaseResult RunFakeForegroundReadExceptionCase()
    {
        var result = new CleanupCaseResult(
            "FG10",
            "foreground read exception is diagnosed separately");
        var fake = new FakeForegroundRestoreSurface
        {
            ThrowDuringConfirmationRead = true,
        };
        ForegroundRestoreResult restore = RunFakeForegroundRestore(
            fake,
            () => TakeoverReadResult.Success(false, "FAKE_NO_TAKEOVER"));
        result.Note = ForegroundRestoreToJson(restore).ToJsonString();
        result.Check(!restore.Ok &&
                     restore.Reason == "FOREGROUND_ACTUAL_CONFIRMATION_READ_EXCEPTION:InvalidOperationException",
            "foreground read exception is distinct from normal NULL");
        result.Check(restore.ActualAfterStatus == ForegroundWindowReadStatus.Exception &&
                     !restore.ActualAfterRead,
            "exception status and failed read are recorded");
        result.Check(restore.NullForegroundReadCount == 0 && fake.SetForegroundCalls == 1,
            "exception path does not count NULL or repeat focus requests");
        return result;
    }

    private static CleanupCaseResult RunFakeInitialForegroundNullCase()
    {
        var result = new CleanupCaseResult(
            "FG11",
            "initial NULL foreground capture prevents test start");
        bool created = false;
        string reason = CaptureOriginalStateNullForFake(ref created);
        result.Note = J.Obj(
            ("reason", J.N(reason)),
            ("controlledWindowCreated", J.N(created))).ToJsonString();
        result.Check(reason == "ORIGINAL_FOREGROUND_NULL",
            "initial normal NULL has an explicit preflight reason");
        result.Check(!created, "controlled window is not created after initial NULL");
        return result;
    }

    private static ForegroundRestoreResult RunFakeForegroundRestore(
        FakeForegroundRestoreSurface fake,
        Func<TakeoverReadResult> readTakeover,
        TimeSpan? timeout = null)
    {
        long fakeNowMs = 0;
        return ForegroundRestoreVerifier.Restore(
            fake.OriginalWindow,
            originalWindowCaptured: true,
            fake.IsWindow,
            fake.GetForegroundWindow,
            fake.SetForegroundWindow,
            readTakeover,
            timeout ?? TimeSpan.FromMilliseconds(50),
            TimeSpan.FromMilliseconds(5),
            nowMilliseconds: () => fakeNowMs,
            wait: delay => fakeNowMs += Math.Max(1, (long)Math.Ceiling(delay.TotalMilliseconds)));
    }

    private static JsonObject ForegroundRestoreToJson(ForegroundRestoreResult result) => J.Obj(
        ("ok", J.N(result.Ok)),
        ("skipped", J.N(result.Skipped)),
        ("userTakeover", J.N(result.UserTakeover)),
        ("reason", J.N(result.Reason)),
        ("originalWindow", J.N(result.OriginalWindow.ToInt64())),
        ("originalWindowValid", J.N(result.OriginalWindowValid)),
        ("actualBefore", J.N(result.ActualBefore.ToInt64())),
        ("actualBeforeRead", J.N(result.ActualBeforeRead)),
        ("setForegroundCalled", J.N(result.SetForegroundCalled)),
        ("setForegroundReturned", J.N(result.SetForegroundReturned)),
        ("actualAfter", J.N(result.ActualAfter.ToInt64())),
        ("actualAfterRead", J.N(result.ActualAfterRead)),
        ("actualBeforeStatus", J.N(result.ActualBeforeStatus.ToString())),
        ("actualAfterStatus", J.N(result.ActualAfterStatus.ToString())),
        ("nullForegroundReadCount", J.N(result.NullForegroundReadCount)),
        ("pollCount", J.N(result.PollCount)),
        ("takeoverReadCount", J.N(result.TakeoverReadCount)),
        ("elapsedMs", J.N(result.ElapsedMs)));

    /// <summary>Deterministic L4 runner path: A -> B -> A belongs to B, then
    /// A -> pre-window-original belongs to harness cleanup.</summary>
    private static CleanupCaseResult RunFakePreparedL4Case()
    {
        const long targetId = Fixture.TargetId;
        const int operationX = 10;
        const int operationY = 10;
        const int prepareX = 50;
        const int prepareY = 60;
        const int originalX = 0;
        const int originalY = 0;
        var result = new CleanupCaseResult(
            "LF01",
            "injectable L4 distinguishes guard prepare/restore from harness cleanup restore");
        var eventRecorder = new LiveEventRecorder();
        var observer = new FakeInputObserver();
        var focus = new FakeFocusSnapshotProvider();
        focus.SetTarget(targetId);
        focus.SetForeground(targetId);
        var cursor = new FakeCursorBackend(operationX, operationY);
        var raw = new CountingRawInputBackend();
        var trace = new BarrierTraceSink(null, TimeSpan.Zero, eventRecorder, "L4-fake");
        var guard = new InputSafetyGuard(
            observer,
            focus,
            cursor,
            raw,
            trace,
            new InputSafetyOptions
            {
                MarkerFactory = () => 0x100000F4UL,
                RestoreCursorOnCleanRelease = true,
            });
        observer.Start(evt =>
        {
            eventRecorder.RecordObserved("L4-fake", evt);
            guard.OnObservedInput(evt);
        });

        ArmOutcome arm = guard.Arm(new ArmRequest(targetId));
        long setBefore = cursor.SetCallCount;
        InputActionOutcome outcome = guard.Execute(InputAction.WheelWithPrepare(120, prepareX, prepareY));
        long guardCursorCalls = cursor.SetCallCount - setBefore;
        (int X, int Y) afterGuardOperation = cursor.GetPosition();
        long beforeRelease = cursor.SetCallCount;
        ReleaseOutcome release = guard.Release();
        long afterRelease = cursor.SetCallCount;

        CleanupReceipt receipt = CleanupCoordinator.Run(
            "L4-fake",
            "injectable L4",
            new CleanupSurface
            {
                StopNewActions = () => release.Ok
                    ? CleanupActionResult.Success(release.Reason)
                    : CleanupActionResult.Failure(release.Reason),
                ReadTakeover = () => TakeoverReadResult.Success(false),
                RestoreCursorWithoutTakeover = () =>
                {
                    bool ok = cursor.SetPosition(originalX, originalY);
                    (int X, int Y) final = cursor.GetPosition();
                    return ok && final == (originalX, originalY)
                        ? CleanupActionResult.Success("HARNESS_PRE_WINDOW_CURSOR_RESTORE_OK")
                        : CleanupActionResult.Failure("HARNESS_PRE_WINDOW_CURSOR_RESTORE_FAILED");
                },
                PreserveUserCursor = () => CleanupActionResult.Failure("UNEXPECTED_TAKEOVER"),
                StopObserver = () =>
                {
                    observer.Stop();
                    return CleanupActionResult.Success("FAKE_OBSERVER_STOPPED");
                },
                ShutdownWindow = () => CleanupActionResult.Success("FAKE_WINDOW_EXITED"),
                RestoreForegroundWithoutTakeover = () => CleanupActionResult.Success("FAKE_FOREGROUND_RESTORED"),
                PreserveUserForeground = () => CleanupActionResult.Failure("UNEXPECTED_TAKEOVER"),
                WindowThreadAlive = () => false,
                DisposeSynchronizationIfSafe = () => CleanupActionResult.Success("FAKE_SYNC_DISPOSED"),
            });
        (int X, int Y) finalCursor = cursor.GetPosition();

        result.Receipt = receipt;
        result.Note = J.Obj(
            ("armOk", J.N(arm.Ok)),
            ("operationBefore", J.Obj(("x", J.N(operationX)), ("y", J.N(operationY)))),
            ("prepare", J.Obj(("x", J.N(prepareX)), ("y", J.N(prepareY)))),
            ("guardCursorCalls", J.N(guardCursorCalls)),
            ("afterGuardX", J.N(afterGuardOperation.X)),
            ("afterGuardY", J.N(afterGuardOperation.Y)),
            ("beforeReleaseCursorCalls", J.N(beforeRelease)),
            ("afterReleaseCursorCalls", J.N(afterRelease)),
            ("finalX", J.N(finalCursor.X)),
            ("finalY", J.N(finalCursor.Y))).ToJsonString();
        result.Check(arm.Ok, "fake L4 arm succeeds");
        result.Check(outcome.Ok && outcome.SendCallCount == 1 && outcome.InputsSentCount == 1,
            "prepared vertical action reaches one raw call and one accepted input");
        result.Check((prepareX, prepareY) != (operationX, operationY), "prepare point differs from operation point");
        result.Check(guardCursorCalls == 2, "B performs exactly prepare and restore cursor calls");
        result.Check(outcome.CursorRestoreAttempted && outcome.CursorRestored,
            "B reports a successful per-operation cursor restore");
        result.Check(afterGuardOperation == (operationX, operationY), "B restores from prepare point back to operation point");
        result.Check(beforeRelease == afterRelease, "Release does not duplicate B's completed restore");
        result.Check(receipt.Passed, "harness cleanup succeeds after B restore");
        result.Check(cursor.SetCallCount == 3 && finalCursor == (originalX, originalY),
            "harness performs one separate pre-window restore to the final coordinate");
        return result;
    }

    private static CleanupCaseResult RunCleanupCase(string id, string description, Func<CleanupCaseResult> run)
    {
        try
        {
            CleanupCaseResult result = run();
            return result;
        }
        catch (Exception ex)
        {
            var result = new CleanupCaseResult(id, description)
            {
                Note = ex.ToString(),
            };
            result.Check(false, "Unhandled " + ex.GetType().Name + ": " + ex.Message);
            return result;
        }
    }

    private static bool OrderIs(CleanupReceipt receipt, params string[] sequence)
    {
        int previous = -1;
        foreach (string name in sequence)
        {
            int current = receipt.Order.IndexOf(name);
            if (current <= previous)
            {
                return false;
            }

            previous = current;
        }

        return true;
    }

    private static string CaptureOriginalStateForFake(bool foregroundRead, bool cursorRead, ref bool created)
    {
        if (!foregroundRead)
        {
            return "ORIGINAL_FOREGROUND_READ_FAILED";
        }

        if (!cursorRead)
        {
            return "ORIGINAL_CURSOR_READ_FAILED";
        }

        created = true;
        return "OK";
    }

    private static string CaptureOriginalStateNullForFake(ref bool created)
    {
        created = false;
        return "ORIGINAL_FOREGROUND_NULL";
    }

    private sealed class LiveScenarioResult
    {
        public LiveScenarioResult(string id, string description)
        {
            Id = id;
            Description = description;
        }

        public string Id { get; }

        public string Description { get; }

        public bool Passed { get; set; }

        public string Reason { get; set; } = string.Empty;

        public long RawCalls { get; set; }

        public long Accepted { get; set; }

        public long WindowMessages { get; set; }

        public bool UserTakeover { get; set; }

        public bool WindowCreated { get; set; }

        public bool ForegroundAcquired { get; set; }

        public bool HookStarted { get; set; }

        public string ObserverStartReason { get; set; } = string.Empty;

        public bool RawBackendReached { get; set; }

        public bool MarkerBoundaryChecked { get; set; }

        public bool MarkerBoundaryMatch { get; set; }

        public bool SelfTakeoverAbsent { get; set; }

        public string InternalMarkerHex { get; set; } = string.Empty;

        public string ManagedInputMarkerHex { get; set; } = string.Empty;

        public string NativeInputMarkerHex { get; set; } = string.Empty;

        public List<string> HookMarkerHexes { get; } = new();

        public long CursorSetCalls { get; set; }

        public long HarnessCursorSetCalls { get; set; }

        public long HarnessCursorSetupCalls { get; set; }

        public long HarnessCleanupCursorSetCalls { get; set; }

        public bool GuardCursorRestoreAttempted { get; set; }

        public bool GuardCursorRestored { get; set; }

        public bool HarnessCursorRestored { get; set; }

        public bool CancelBeforePrepare { get; set; }

        public bool ExecutionThreadExited { get; set; } = true;

        public bool ExecutionOutcomeOk { get; set; }

        public string ExecutionStage { get; set; } = string.Empty;

        public string ExecutionReason { get; set; } = string.Empty;

        public string ExecutionException { get; set; } = string.Empty;

        public bool PhysicalMouseMoveObserved { get; set; }

        public int ObservedEventCount { get; set; }

        public bool UserPositionUnchanged { get; set; }

        public bool ProgramDidNotInterfereWithUserPosition { get; set; }

        public (int X, int Y)? HarnessCursorBefore { get; set; }

        public (int X, int Y)? GuardCursorBefore { get; set; }

        public (int X, int Y)? PrepareTarget { get; set; }

        public (int X, int Y)? CursorAfterOperation { get; set; }

        public (int X, int Y)? FinalCursor { get; set; }

        public JsonObject? CursorAfterCleanupObservation { get; set; }

        public ObservedInputEvent? PhysicalMouseMove { get; set; }

        public bool L5BarrierReady { get; set; }

        public long L5BarrierReadyNs { get; set; }

        public bool L5PromptDisplayed { get; set; }

        public string L5PromptReason { get; set; } = string.Empty;

        public long L5PromptNs { get; set; }

        public long L5ManualWaitStartedNs { get; set; }

        public long L5ManualWaitEndedNs { get; set; }

        public ObserverDiagnostics? ObserverBeforeWait { get; set; }

        public ObserverDiagnostics? ObserverAfterWait { get; set; }

        public ObserverDiagnostics? ObserverAfterCleanup { get; set; }

        public JsonArray L5MouseEvents { get; } = new();

        public JsonArray L5MouseEventsAfterCleanup { get; } = new();

        public long L5CleanupStartNs { get; set; }

        public long L5CleanupEndNs { get; set; }

        public CleanupReceipt? Cleanup { get; set; }

        public JsonObject ToJson()
        {
            JsonNode? Point((int X, int Y)? point) => point is { } value
                ? J.Obj(("x", J.N(value.X)), ("y", J.N(value.Y)))
                : null;

            JsonNode? PhysicalMove() => PhysicalMouseMove is { } observed
                ? J.Obj(
                     ("kind", J.N(observed.Kind.ToString())),
                     ("device", J.N(observed.Device.ToString())),
                     ("origin", J.N(observed.Origin.ToString())),
                     ("classification", J.N(observed.Origin.ToString())),
                     ("nativeFlags", J.N((long)observed.NativeFlags)),
                     ("nativeFlagsHex", J.N(J.Hex(observed.NativeFlags))),
                     ("x", J.N(observed.X)),
                    ("y", J.N(observed.Y)),
                    ("monotonicNs", J.N(observed.MonotonicNs)),
                    ("sequence", J.N(observed.Sequence)))
                : null;

            return J.Obj(
                ("id", J.N(Id)),
                ("description", J.N(Description)),
                ("status", J.N(Passed ? "PASS" : "FAIL")),
                ("reason", J.N(Reason)),
                ("rawCalls", J.N(RawCalls)),
                ("accepted", J.N(Accepted)),
                ("windowMessages", J.N(WindowMessages)),
                ("userTakeover", J.N(UserTakeover)),
                ("windowCreated", J.N(WindowCreated)),
                ("foregroundAcquired", J.N(ForegroundAcquired)),
                ("hookStarted", J.N(HookStarted)),
                ("rawBackendReached", J.N(RawBackendReached)),
                ("markerBoundary", J.Obj(
                    ("checked", J.N(MarkerBoundaryChecked)),
                    ("match", J.N(MarkerBoundaryMatch)),
                    ("selfTakeoverAbsent", J.N(SelfTakeoverAbsent)),
                    ("internalMarkerHex", J.N(InternalMarkerHex)),
                    ("managedInputRecordExtraInfoHex", J.N(ManagedInputMarkerHex)),
                    ("nativePassedExtraInfoHex", J.N(NativeInputMarkerHex)),
                    ("hookReceivedExtraInfoHex", new JsonArray(HookMarkerHexes.Select(J.N).ToArray())))),
                ("observedEventCount", J.N(ObservedEventCount)),
                ("cursorSetCalls", J.N(CursorSetCalls)),
                ("harnessCursorSetCalls", J.N(HarnessCursorSetCalls)),
                ("harnessCursorSetupCalls", J.N(HarnessCursorSetupCalls)),
                ("harnessCleanupCursorSetCalls", J.N(HarnessCleanupCursorSetCalls)),
                ("guardCursorRestoreAttempted", J.N(GuardCursorRestoreAttempted)),
                ("guardCursorRestored", J.N(GuardCursorRestored)),
                ("harnessCursorRestored", J.N(HarnessCursorRestored)),
                ("cancelBeforePrepare", J.N(CancelBeforePrepare)),
                ("programDidNotInterfereWithUserPosition", J.N(ProgramDidNotInterfereWithUserPosition)),
                ("execution", J.Obj(
                    ("threadExited", J.N(ExecutionThreadExited)),
                    ("outcomeOk", J.N(ExecutionOutcomeOk)),
                    ("stage", J.N(ExecutionStage)),
                    ("reason", J.N(ExecutionReason)),
                    ("exception", J.N(ExecutionException)))),
                ("cursor", J.Obj(
                    ("harnessBeforeWindow", Point(HarnessCursorBefore)),
                    ("guardBeforeOperation", Point(GuardCursorBefore)),
                    ("prepareTarget", Point(PrepareTarget)),
                    ("afterOperation", Point(CursorAfterOperation)),
                    ("afterCleanupObservation", CursorAfterCleanupObservation))),
                ("physicalMouseMove", PhysicalMove()),
                ("l5Diagnostic", J.Obj(
                    ("barrierReady", J.N(L5BarrierReady)),
                    ("barrierReadyNs", J.N(L5BarrierReadyNs)),
                    ("promptDisplayed", J.N(L5PromptDisplayed)),
                    ("promptReason", J.N(L5PromptReason)),
                    ("promptNs", J.N(L5PromptNs)),
                    ("manualWaitStartedNs", J.N(L5ManualWaitStartedNs)),
                    ("manualWaitEndedNs", J.N(L5ManualWaitEndedNs)),
                    ("observerStartReason", J.N(ObserverStartReason)),
                    ("observerBeforeWait", ObserverDiagnosticsJson(ObserverBeforeWait)),
                    ("observerAfterWait", ObserverDiagnosticsJson(ObserverAfterWait)),
                    ("observerAfterCleanup", ObserverDiagnosticsJson(ObserverAfterCleanup)),
                    ("cleanupStartNs", J.N(L5CleanupStartNs)),
                    ("cleanupEndNs", J.N(L5CleanupEndNs)),
                    ("mouseEventsAtWaitSnapshot", L5MouseEvents.DeepClone()),
                    ("mouseEventsAtCleanupSnapshot", L5MouseEventsAfterCleanup.DeepClone()))),
                ("cleanup", Cleanup?.ToJson()));
        }
    }

    private static LiveScenarioResult RunLiveScenario(
        string scenario,
        int manualTimeoutMs,
        LiveEventRecorder eventRecorder)
    {
        string description = scenario switch
        {
            "L1" => "controlled-window preflight, arm, duplicate arm, cancel and release",
            "L2" => "one vertical wheel raw call",
            "L3" => "one horizontal wheel raw call",
            "L4" => "one prepared vertical wheel raw call",
            "L5" => "manual physical mouse takeover with bounded wait",
            _ => scenario,
        };
        var result = new LiveScenarioResult(scenario, description);

        ControlledWindowHarness? harness = null;
        Win32LowLevelInputObserver? observer = null;
        InputSafetyGuard? guard = null;
        Win32RawInputBackend? raw = null;
        Win32CursorBackend? cursor = null;
        LiveTakeoverRecorder? takeoverRecorder = null;
        BarrierTraceSink? trace = null;
        bool observerStarted = false;
        bool cleanupDone = false;
        long harnessCursorCallsBeforeOperation = 0;
        long harnessCursorCallsAfterSetup = 0;

        try
        {
            harness = ControlledWindowHarness.Create();
            result.WindowCreated = harness.Created;
            result.ForegroundAcquired = harness.ForegroundAcquired;
            result.HarnessCursorBefore = harness.OriginalCursorCaptured ? harness.CursorBefore : null;
            eventRecorder.Record(
                scenario,
                "harness_original_state",
                ("captured", J.N(harness.OriginalStateCaptured)),
                ("foregroundCaptured", J.N(harness.OriginalForegroundCaptured)),
                ("cursorCaptured", J.N(harness.OriginalCursorCaptured)),
                ("foreground", J.N(harness.PreviousForeground.ToInt64())),
                ("cursorX", J.N(harness.CursorBefore.X)),
                ("cursorY", J.N(harness.CursorBefore.Y)),
                ("error", J.N(harness.LastError)));
            if (!harness.OriginalStateCaptured || !harness.Created || !harness.ForegroundAcquired)
            {
                result.Reason = string.IsNullOrEmpty(harness.LastError) ? "WINDOW_PREFLIGHT_FAILED" : harness.LastError;
                return result;
            }

            harness.WindowMessageObserver = message => eventRecorder.Record(
                scenario,
                "window_message",
                ("message", J.N(message)),
                ("wheelMessages", J.N(harness.WheelMessages)),
                ("horizontalWheelMessages", J.N(harness.HorizontalWheelMessages)),
                ("moveMessages", J.N(harness.MoveMessages)),
                ("buttonMessages", J.N(harness.ButtonMessages)));

            observer = new Win32LowLevelInputObserver("v2-2b-live-" + scenario);
            cursor = new Win32CursorBackend();
            raw = new Win32RawInputBackend();

            var operationBefore = (harness.OriginX + 80, harness.OriginY + 70);
            if (operationBefore == harness.CursorBefore)
            {
                operationBefore = (harness.OriginX + 100, harness.OriginY + 70);
            }

            var prepareTarget = (harness.OriginX + 240, harness.OriginY + 120);
            if (prepareTarget == operationBefore)
            {
                prepareTarget = (harness.OriginX + 220, harness.OriginY + 100);
            }

            result.PrepareTarget = scenario == "L4" ? prepareTarget : null;
            harnessCursorCallsBeforeOperation = harness.HarnessCursorSetCalls;
            if (!harness.PlaceCursor(operationBefore.Item1, operationBefore.Item2))
            {
                result.Reason = "CONTROLLED_CURSOR_PLACE_FAILED";
                return result;
            }

            harnessCursorCallsAfterSetup = harness.HarnessCursorSetCalls;
            result.GuardCursorBefore = cursor.GetPosition();
            eventRecorder.Record(
                scenario,
                "harness_cursor_setup",
                ("x", J.N(operationBefore.Item1)),
                ("y", J.N(operationBefore.Item2)),
                ("harnessSetCalls", J.N(harness.HarnessCursorSetCalls)),
                ("guardSavedCursorX", J.N(result.GuardCursorBefore.Value.X)),
                ("guardSavedCursorY", J.N(result.GuardCursorBefore.Value.Y)));

            trace = new BarrierTraceSink(
                scenario == "L5" ? TracePhase.Precheck1Pass : null,
                TimeSpan.FromMilliseconds(manualTimeoutMs + 1000),
                eventRecorder,
                scenario);
            var focus = new LiveFocusSnapshotProvider(harness.Hwnd.ToInt64());
            guard = new InputSafetyGuard(
                observer,
                focus,
                cursor,
                raw,
                trace,
                new InputSafetyOptions { RestoreCursorOnCleanRelease = true });
            trace.SetTimeoutCancellation(() => guard.Cancel("BARRIER_TIMEOUT"));
            takeoverRecorder = new LiveTakeoverRecorder(() => guard.Ledger.Marker);

            ObserverStartOutcome started = observer.Start(evt =>
            {
                eventRecorder.RecordObserved(scenario, evt);
                takeoverRecorder.Record(evt);
                guard.OnObservedInput(evt);
            });
            observerStarted = started.Ok;
            result.HookStarted = started.Ok;
            result.ObserverStartReason = started.Reason;
            if (!started.Ok)
            {
                result.Reason = "OBSERVER_START:" + started.Reason;
                return result;
            }

            ArmOutcome arm = guard.Arm(new ArmRequest(harness.Hwnd.ToInt64()));
            if (!arm.Ok)
            {
                result.Reason = "ARM:" + arm.Reason;
                return result;
            }

            if (scenario == "L1")
            {
                ArmOutcome duplicate = guard.Arm(new ArmRequest(harness.Hwnd.ToInt64()));
                CancelOutcome cancel = guard.Cancel("L1_CANCEL");
                result.Passed = !duplicate.Ok && cancel.Ok && raw.SendCallCount == 0;
                result.Reason = result.Passed ? "OK" : "L1_STATE_CHECK_FAILED";
                return result;
            }

            if (scenario == "L5")
            {
                RunManualTakeover(
                    result,
                    guard,
                    raw,
                    cursor,
                    trace,
                    takeoverRecorder,
                    eventRecorder,
                    manualTimeoutMs,
                    observer,
                    harness);
                return result;
            }

            InputAction action = scenario switch
            {
                "L2" => InputAction.Wheel(120),
                "L3" => InputAction.HorizontalWheel(120),
                "L4" => InputAction.WheelWithPrepare(120, prepareTarget.Item1, prepareTarget.Item2),
                _ => throw new InvalidOperationException("Unknown live scenario " + scenario),
            };

            long rawBefore = raw.SendCallCount;
            long acceptedBefore = raw.InputsSentCount;
            long cursorBefore = cursor.SetCallCount;
            long messagesBefore = scenario == "L3" ? harness.HorizontalWheelMessages : harness.WheelMessages;
            eventRecorder.Record(
                scenario,
                "action_begin",
                ("fingerprint", J.N(action.Fingerprint)),
                ("cursorSetCallsBefore", J.N(cursorBefore)),
                ("rawCallsBefore", J.N(rawBefore)),
                ("acceptedBefore", J.N(acceptedBefore)),
                ("windowMessagesBefore", J.N(messagesBefore)));
            InputActionOutcome outcome = guard.Execute(action);
            long messageCount = scenario == "L3"
                ? WaitForMessage(() => harness.HorizontalWheelMessages, messagesBefore + 1, 1000)
                : WaitForMessage(() => harness.WheelMessages, messagesBefore + 1, 1000);

            result.RawCalls = raw.SendCallCount - rawBefore;
            result.Accepted = raw.InputsSentCount - acceptedBefore;
            result.RawBackendReached = result.RawCalls > 0;
            result.CursorSetCalls = cursor.SetCallCount - cursorBefore;
            result.CursorAfterOperation = cursor.GetPosition();
            result.WindowMessages = messageCount - messagesBefore;
            result.GuardCursorRestoreAttempted = outcome.CursorRestoreAttempted;
            result.GuardCursorRestored = outcome.CursorRestored;
            result.ExecutionOutcomeOk = outcome.Ok;
            result.ExecutionStage = outcome.Stage;
            result.ExecutionReason = outcome.Reason;

            InputEventKind expectedObservedKind = scenario == "L3"
                ? InputEventKind.MouseHorizontalWheel
                : InputEventKind.MouseWheel;
            IReadOnlyList<ObservedInputEvent> observedEvents =
                takeoverRecorder?.SnapshotEvents() ?? Array.Empty<ObservedInputEvent>();
            ObservedInputEvent[] actionObservedEvents = observedEvents
                .Where(observed => observed.Kind == expectedObservedKind)
                .ToArray();
            result.HookMarkerHexes.AddRange(actionObservedEvents.Select(observed => J.Hex(observed.ExtraInfo)));
            TakeoverReadResult afterActionTakeover = takeoverRecorder?.Read() ??
                TakeoverReadResult.Failure("TAKEOVER_MONITOR_NOT_INITIALIZED");
            result.SelfTakeoverAbsent = afterActionTakeover.Ok && !afterActionTakeover.Seen;
            eventRecorder.Record(
                scenario,
                "takeover_check_after_action",
                ("ok", J.N(afterActionTakeover.Ok)),
                ("seen", J.N(afterActionTakeover.Seen)),
                ("reason", J.N(afterActionTakeover.Reason)));

            if (raw.SentExtraInfo.Count > 0 && raw.NativeExtraInfo.Count > 0 && actionObservedEvents.Length > 0)
            {
                int managedLast = raw.SentExtraInfo.Count - 1;
                int nativeLast = raw.NativeExtraInfo.Count - 1;
                result.InternalMarkerHex = J.Hex(guard.Ledger.Marker);
                result.ManagedInputMarkerHex = J.Hex(raw.SentExtraInfo[managedLast]);
                result.NativeInputMarkerHex = J.Hex(raw.NativeExtraInfo[nativeLast]);
                result.MarkerBoundaryChecked = raw.SentExtraInfo.Count == raw.NativeExtraInfo.Count &&
                                                actionObservedEvents.Length == 1;
                result.MarkerBoundaryMatch = result.MarkerBoundaryChecked &&
                                              guard.Ledger.Marker == raw.SentExtraInfo[managedLast] &&
                                              guard.Ledger.Marker == raw.NativeExtraInfo[nativeLast] &&
                                              guard.Ledger.Marker == actionObservedEvents[0].ExtraInfo;
            }

            if (raw.NativeExtraInfo.Count > 0)
            {
                int last = raw.NativeExtraInfo.Count - 1;
                NativeInputMethods.NativeMarkerBoundaryDiagnostics boundary =
                    NativeInputMethods.InspectMarker(guard.Ledger.Marker);
                var hookValues = new JsonArray(
                    observedEvents
                        .Select(observed => (JsonNode?)J.N(J.Hex(observed.ExtraInfo)))
                        .ToArray());
                eventRecorder.Record(
                    scenario,
                    "marker_boundary",
                    ("transportBits", J.N(InputMarker.TransportBits)),
                    ("processPointerBits", J.N(boundary.ProcessPointerBits)),
                    ("uIntPtrBits", J.N(boundary.UIntPtrBits)),
                    ("inputSizeBytes", J.N(boundary.InputSizeBytes)),
                    ("mouseInputSizeBytes", J.N(boundary.MouseInputSizeBytes)),
                    ("mouseInputExtraInfoOffsetBytes", J.N(boundary.MouseInputExtraInfoOffsetBytes)),
                    ("msllHookStructSizeBytes", J.N(boundary.MsllHookStructSizeBytes)),
                    ("msllHookStructExtraInfoOffsetBytes", J.N(boundary.MsllHookStructExtraInfoOffsetBytes)),
                    ("internalMarkerHex", J.N(J.Hex(guard.Ledger.Marker))),
                    ("managedInputRecordExtraInfoHex", J.N(J.Hex(raw.SentExtraInfo[last]))),
                    ("nativePassedExtraInfoHex", J.N(J.Hex(raw.NativeExtraInfo[last]))),
                    ("marshaledExtraInfoHex", J.N(J.Hex(boundary.MarshaledExtraInfo))),
                    ("hookReceivedExtraInfoHex", hookValues),
                    ("selfTakeoverAbsent", J.N(result.SelfTakeoverAbsent)));
            }

            bool commonPassed = outcome.Ok && result.RawCalls == 1 && result.Accepted == 1 &&
                                result.WindowMessages == 1 && result.MarkerBoundaryChecked &&
                                result.MarkerBoundaryMatch && result.SelfTakeoverAbsent;
            bool l4CursorPassed = scenario != "L4" ||
                                  (prepareTarget != operationBefore &&
                                   result.CursorSetCalls == 2 &&
                                   outcome.CursorRestoreAttempted &&
                                   outcome.CursorRestored &&
                                   result.CursorAfterOperation == operationBefore);
            result.Passed = commonPassed && l4CursorPassed;
            result.Reason = result.Passed
                ? "OK"
                : !outcome.Ok
                    ? "ACTION_OR_MESSAGE_COUNT_FAILED:" + outcome.Reason
                    : !result.MarkerBoundaryMatch
                        ? "MARKER_BOUNDARY_FAILED"
                        : !result.SelfTakeoverAbsent
                            ? "SELF_TAKEOVER_DETECTED"
                            : "ACTION_OR_MESSAGE_COUNT_FAILED:" + outcome.Reason;
            eventRecorder.Record(
                scenario,
                "action_result",
                ("ok", J.N(outcome.Ok)),
                ("stage", J.N(outcome.Stage)),
                ("reason", J.N(outcome.Reason)),
                ("rawCalls", J.N(result.RawCalls)),
                ("accepted", J.N(result.Accepted)),
                ("cursorSetCalls", J.N(result.CursorSetCalls)),
                ("cursorAfterX", J.N(result.CursorAfterOperation.Value.X)),
                ("cursorAfterY", J.N(result.CursorAfterOperation.Value.Y)),
                ("windowMessages", J.N(result.WindowMessages)),
                ("guardCursorRestoreAttempted", J.N(outcome.CursorRestoreAttempted)),
                ("guardCursorRestored", J.N(outcome.CursorRestored)),
                ("markerBoundaryChecked", J.N(result.MarkerBoundaryChecked)),
                ("markerBoundaryMatch", J.N(result.MarkerBoundaryMatch)),
                ("selfTakeoverAbsent", J.N(result.SelfTakeoverAbsent)));
            return result;
        }
        catch (Exception ex)
        {
            result.Passed = false;
            result.Reason = "EXCEPTION:" + ex.GetType().Name;
            result.ExecutionException = ex.ToString();
            eventRecorder.Record(scenario, "runner_exception", ("exception", J.N(ex.ToString())));
            return result;
        }
        finally
        {
            if (harness is not null)
            {
                if (harness.Created && guard is not null && observer is not null && cursor is not null && raw is not null)
                {
                    if (takeoverRecorder is null || trace is null)
                    {
                        result.Passed = false;
                        result.Reason = "CLEANUP_MONITOR_NOT_INITIALIZED";
                    }

                    TakeoverReadResult? foregroundSetRead = null;
                    var foregroundConfirmationReads = new List<TakeoverReadResult>();
                    if (scenario == "L5")
                    {
                        result.L5CleanupStartNs = TraceClock.NowNs();
                    }
                    CleanupReceipt receipt = CleanupCoordinator.Run(
                        scenario,
                        description,
                        new CleanupSurface
                        {
                            StopNewActions = () =>
                            {
                                ReleaseOutcome release = guard.Release();
                                eventRecorder.Record(
                                    scenario,
                                    "guard_release",
                                    ("ok", J.N(release.Ok)),
                                    ("reason", J.N(release.Reason)),
                                    ("cursorRestoreAttempted", J.N(release.CursorRestoreAttempted)),
                                    ("cursorRestoreSkipped", J.N(release.CursorRestoreSkipped)),
                                    ("cursorRestored", J.N(release.CursorRestored)),
                                    ("cursorRestoreReason", J.N(release.CursorRestoreReason)));
                                return release.Ok
                                    ? CleanupActionResult.Success(release.Reason)
                                    : CleanupActionResult.Failure(release.Reason);
                            },
                            ReadTakeover = () =>
                            {
                                TakeoverReadResult read = takeoverRecorder?.Read() ??
                                    TakeoverReadResult.Failure("TAKEOVER_MONITOR_NOT_INITIALIZED");
                                eventRecorder.Record(
                                    scenario,
                                    "takeover_check",
                                    ("ok", J.N(read.Ok)),
                                    ("seen", J.N(read.Seen)),
                                    ("reason", J.N(read.Reason)));
                                return read;
                            },
                            RestoreCursorWithoutTakeover = () =>
                            {
                                bool ok = harness.RestoreOriginalCursor();
                                eventRecorder.Record(
                                    scenario,
                                    "harness_cursor_restore",
                                    ("ok", J.N(ok)),
                                    ("reason", J.N(harness.CursorRestoreReason)),
                                    ("setCalls", J.N(harness.HarnessCursorSetCalls)),
                                    ("finalReadSucceeded", J.N(harness.CursorAfterReadSucceeded)),
                                    ("finalX", J.N(harness.CursorAfter.X)),
                                    ("finalY", J.N(harness.CursorAfter.Y)));
                                return ok
                                    ? CleanupActionResult.Success(harness.CursorRestoreReason)
                                    : CleanupActionResult.Failure(harness.CursorRestoreReason);
                            },
                            PreserveUserCursor = () =>
                            {
                                bool ok = harness.PreserveUserCursor();
                                eventRecorder.Record(
                                    scenario,
                                    "harness_cursor_preserve",
                                    ("ok", J.N(ok)),
                                    ("reason", J.N(harness.CursorRestoreReason)),
                                    ("setCalls", J.N(harness.HarnessCursorSetCalls)),
                                    ("finalReadSucceeded", J.N(harness.CursorAfterReadSucceeded)),
                                    ("finalX", J.N(harness.CursorAfter.X)),
                                    ("finalY", J.N(harness.CursorAfter.Y)));
                                return ok
                                    ? CleanupActionResult.Skip(harness.CursorRestoreReason)
                                    : CleanupActionResult.Failure(harness.CursorRestoreReason);
                            },
                            RestoreForegroundWithoutTakeover = () =>
                            {
                                foregroundSetRead = takeoverRecorder?.Read() ??
                                    TakeoverReadResult.Failure("TAKEOVER_MONITOR_NOT_INITIALIZED");
                                eventRecorder.Record(
                                    scenario,
                                    "takeover_check_before_foreground_set",
                                    ("ok", J.N(foregroundSetRead.Value.Ok)),
                                    ("seen", J.N(foregroundSetRead.Value.Seen)),
                                    ("reason", J.N(foregroundSetRead.Value.Reason)));
                                if (!foregroundSetRead.Value.Ok)
                                {
                                    return CleanupActionResult.Failure("TAKEOVER_STATE_READ_FAILED_SKIP_FOREGROUND_RESTORE");
                                }

                                if (foregroundSetRead.Value.Seen)
                                {
                                    return CleanupActionResult.Skip("TAKEOVER_DETECTED_BEFORE_FOREGROUND_SET");
                                }

                                bool ok = harness.RestorePreviousForeground(
                                    () =>
                                    {
                                        TakeoverReadResult read = takeoverRecorder?.Read() ??
                                            TakeoverReadResult.Failure("TAKEOVER_MONITOR_NOT_INITIALIZED");
                                        foregroundConfirmationReads.Add(read);
                                        eventRecorder.Record(
                                            scenario,
                                            "takeover_check_foreground_confirmation",
                                            ("ok", J.N(read.Ok)),
                                            ("seen", J.N(read.Seen)),
                                            ("reason", J.N(read.Reason)),
                                            ("sample", J.N(foregroundConfirmationReads.Count)));
                                        return read;
                                    },
                                    TimeSpan.FromMilliseconds(ForegroundRestoreConfirmationTimeoutMs),
                                    TimeSpan.FromMilliseconds(ForegroundRestorePollMs));
                                eventRecorder.Record(
                                    scenario,
                                    "harness_foreground_restore",
                                    ("ok", J.N(ok)),
                                    ("reason", J.N(harness.ForegroundRestoreReason)),
                                    ("attempted", J.N(harness.ForegroundRestoreAttempted)),
                                    ("originalWindow", J.N(harness.PreviousForeground.ToInt64())),
                                    ("originalWindowValid", J.N(harness.ForegroundRestoreOriginalWindowValid)),
                                    ("actualForegroundBefore", J.N(harness.ForegroundBeforeRestore.ToInt64())),
                                    ("actualBeforeReadSucceeded", J.N(harness.ForegroundBeforeRestoreReadSucceeded)),
                                    ("setForegroundCalled", J.N(harness.ForegroundSetCalled)),
                                    ("setForegroundReturned", J.N(harness.ForegroundSetReturned)),
                                    ("actualForegroundAfter", J.N(harness.ForegroundAfterRestore.ToInt64())),
                                    ("actualAfterReadSucceeded", J.N(harness.ForegroundAfterRestoreReadSucceeded)),
                                    ("actualBeforeStatus", J.N(harness.ForegroundBeforeRestoreStatus.ToString())),
                                    ("actualAfterStatus", J.N(harness.ForegroundAfterRestoreStatus.ToString())),
                                    ("nullForegroundReadCount", J.N(harness.ForegroundNullReadCount)),
                                    ("pollCount", J.N(harness.ForegroundRestorePollCount)),
                                    ("takeoverReadCount", J.N(harness.ForegroundRestoreTakeoverReadCount)),
                                    ("elapsedMs", J.N(harness.ForegroundRestoreElapsedMs)),
                                    ("takeoverDuringConfirmation", J.N(harness.ForegroundRestoreTakeoverDetected)));
                                if (harness.ForegroundRestoreTakeoverDetected)
                                {
                                    return CleanupActionResult.Skip(harness.ForegroundRestoreReason);
                                }
                                return ok
                                    ? CleanupActionResult.Success(harness.ForegroundRestoreReason)
                                    : CleanupActionResult.Failure(harness.ForegroundRestoreReason);
                            },
                            PreserveUserForeground = () =>
                            {
                                bool ok = harness.PreserveUserForeground();
                                eventRecorder.Record(
                                    scenario,
                                    "harness_foreground_preserve",
                                    ("ok", J.N(ok)),
                                    ("reason", J.N(harness.ForegroundRestoreReason)));
                                return ok
                                    ? CleanupActionResult.Skip(harness.ForegroundRestoreReason)
                                    : CleanupActionResult.Failure(harness.ForegroundRestoreReason);
                            },
                            StopObserver = () =>
                            {
                                bool ok = StopObserverAndVerify(
                                    observer,
                                    observerStarted,
                                    out string reason,
                                    out ObserverDiagnostics diagnostics,
                                    out long elapsedMs);
                                eventRecorder.Record(
                                    scenario,
                                    "observer_stop",
                                    ("ok", J.N(ok)),
                                    ("reason", J.N(reason)),
                                    ("elapsedMs", J.N(elapsedMs)),
                                    ("threadAlive", J.N(diagnostics.ThreadAlive)),
                                    ("hooksInstalled", J.N(diagnostics.HooksInstalled)),
                                    ("keyboardHookReleased", J.N(diagnostics.KeyboardHookReleased)),
                                    ("mouseHookReleased", J.N(diagnostics.MouseHookReleased)),
                                    ("lastError", J.N(diagnostics.LastError)));
                                return ok ? CleanupActionResult.Success(reason) : CleanupActionResult.Failure(reason);
                            },
                            ShutdownWindow = () =>
                            {
                                bool ok = harness.ShutdownAndWait(TimeSpan.FromMilliseconds(WindowStopTimeoutMs));
                                eventRecorder.Record(
                                    scenario,
                                    "window_shutdown",
                                    ("ok", J.N(ok)),
                                    ("threadExited", J.N(harness.WindowThreadExited)),
                                    ("threadAlive", J.N(harness.ThreadAlive)),
                                    ("reason", J.N(harness.LastError)));
                                return ok
                                    ? CleanupActionResult.Success("WINDOW_THREAD_EXITED")
                                    : CleanupActionResult.Failure(harness.LastError);
                            },
                            WindowThreadAlive = () => harness.ThreadAlive,
                            DisposeSynchronizationIfSafe = () =>
                            {
                                bool ok = harness.DisposeSynchronizationIfSafe();
                                eventRecorder.Record(
                                    scenario,
                                    "window_sync_dispose",
                                    ("ok", J.N(ok)),
                                    ("disposed", J.N(harness.SynchronizationDisposed)),
                                    ("threadAlive", J.N(harness.ThreadAlive)),
                                    ("reason", J.N(harness.LastError)));
                                return ok
                                    ? CleanupActionResult.Success("WINDOW_SYNC_DISPOSED")
                                    : CleanupActionResult.Failure(harness.LastError);
                            },
                        });
                    if (foregroundSetRead is { } lateRead)
                    {
                        receipt.AddTakeoverCheck("before_foreground_set", lateRead);
                        if (lateRead.Seen)
                        {
                            receipt.UserTakeover = true;
                        }
                    }
                    for (int index = 0; index < foregroundConfirmationReads.Count; index++)
                    {
                        TakeoverReadResult confirmationRead = foregroundConfirmationReads[index];
                        receipt.AddTakeoverCheck(
                            "during_foreground_confirmation_" + (index + 1),
                            confirmationRead);
                        if (confirmationRead.Seen)
                        {
                            receipt.UserTakeover = true;
                        }
                    }

                    if (scenario == "L5")
                    {
                        result.L5CleanupEndNs = TraceClock.NowNs();
                        result.ObserverAfterCleanup = observer.Diagnostics();
                        result.L5MouseEventsAfterCleanup.Clear();
                        foreach (ObservedInputEvent observed in (takeoverRecorder?.SnapshotEvents() ?? Array.Empty<ObservedInputEvent>())
                                     .Where(observed => observed.Device == InputDeviceClass.Mouse &&
                                                        observed.MonotonicNs >= result.L5CleanupStartNs))
                        {
                            result.L5MouseEventsAfterCleanup.Add(MouseEventJson(observed));
                        }
                    }

                    result.Cleanup = receipt;
                    result.UserTakeover = receipt.UserTakeover;
                    result.HarnessCursorRestored = harness.CursorRestored;
                    result.HarnessCursorSetCalls = harness.HarnessCursorSetCalls - harnessCursorCallsBeforeOperation;
                    result.HarnessCursorSetupCalls = harnessCursorCallsAfterSetup - harnessCursorCallsBeforeOperation;
                    result.HarnessCleanupCursorSetCalls = harness.HarnessCursorSetCalls - harnessCursorCallsAfterSetup;
                    result.ObservedEventCount = takeoverRecorder?.EventCount ?? 0;
                    result.Passed = result.Passed && receipt.Passed;
                    if (scenario == "L5")
                    {
                        result.PhysicalMouseMove = takeoverRecorder?.FirstHardwareMouseMoveAfter(result.L5PromptNs);
                        result.PhysicalMouseMoveObserved = result.PhysicalMouseMove is not null;
                        result.FinalCursor = harness.CursorAfterReadSucceeded ? harness.CursorAfter : null;
                        if (harness.CursorAfterReadSucceeded)
                        {
                            result.CursorAfterCleanupObservation = J.Obj(
                                ("stage", J.N("cleanup_complete_read")),
                                ("x", J.N(harness.CursorAfter.X)),
                                ("y", J.N(harness.CursorAfter.Y)),
                                ("observedAtNs", J.N(TraceClock.NowNs())));
                        }

                        result.ProgramDidNotInterfereWithUserPosition =
                            EvaluateL5ProgramNonInterference(result, receipt);
                        result.UserPositionUnchanged = result.ProgramDidNotInterfereWithUserPosition;
                        result.Passed = result.Passed && result.ProgramDidNotInterfereWithUserPosition;
                    }
                    if (!result.Passed && (string.IsNullOrEmpty(result.Reason) || result.Reason == "OK"))
                    {
                        result.Reason = !receipt.Passed
                            ? receipt.FailureReason
                            : scenario == "L5"
                                ? "L5_PROGRAM_NONINTERFERENCE_FAILED"
                                : "VERIFIER_RESULT_FAILED";
                    }

                    if (scenario == "L5" && !result.ProgramDidNotInterfereWithUserPosition &&
                        (string.IsNullOrEmpty(result.Reason) || result.Reason == "OK"))
                    {
                        result.Reason = "L5_PROGRAM_NONINTERFERENCE_FAILED";
                    }

                    eventRecorder.RecordCleanup(scenario, receipt);
                    cleanupDone = true;
                }

                if (!cleanupDone)
                {
                    // Exceptions before the full surface is assembled still use an
                    // auditable fail-closed receipt.  Recovery is skipped because no
                    // valid takeover monitor exists; lifecycle return values are kept.
                    var fallback = new CleanupReceipt(scenario, description)
                    {
                        Passed = false,
                        FailureReason = string.IsNullOrEmpty(result.Reason)
                            ? "CLEANUP_FALLBACK_USED"
                            : result.Reason,
                    };
                    fallback.Add(
                        "cursor_restore_original",
                        ok: false,
                        skipped: true,
                        "CLEANUP_PATH_NOT_INITIALIZED_SKIP_CURSOR_RESTORE");
                    fallback.Add(
                        "foreground_restore_original",
                        ok: false,
                        skipped: true,
                        "CLEANUP_PATH_NOT_INITIALIZED_SKIP_FOREGROUND_RESTORE");

                    bool observerOk = true;
                    string observerReason = "OBSERVER_NOT_STARTED";
                    if (observer is not null)
                    {
                        observerOk = StopObserverAndVerify(
                            observer,
                            observerStarted,
                            out observerReason,
                            out ObserverDiagnostics diagnostics,
                            out long elapsedMs);
                        eventRecorder.Record(
                            scenario,
                            "fallback_observer_stop",
                            ("ok", J.N(observerOk)),
                            ("reason", J.N(observerReason)),
                            ("elapsedMs", J.N(elapsedMs)),
                            ("threadAlive", J.N(diagnostics.ThreadAlive)),
                            ("hooksInstalled", J.N(diagnostics.HooksInstalled)));
                    }

                    fallback.Add("observer_stop", observerOk, skipped: !observerStarted, reason: observerReason);
                    bool windowOk = harness.ShutdownAndWait(TimeSpan.FromMilliseconds(WindowStopTimeoutMs));
                    fallback.Add(
                        "window_shutdown_and_wait",
                        windowOk,
                        skipped: !harness.Created,
                        reason: windowOk ? "WINDOW_THREAD_EXITED" : harness.LastError);
                    bool syncOk = harness.DisposeSynchronizationIfSafe();
                    fallback.Add(
                        "sync_dispose",
                        syncOk,
                        skipped: !syncOk,
                        reason: syncOk ? "WINDOW_SYNC_DISPOSED" : harness.LastError);
                    result.Cleanup = fallback;
                    result.Passed = false;
                    result.Reason = fallback.FailureReason;
                    eventRecorder.RecordCleanup(scenario, fallback);
                    cleanupDone = true;
                }
            }
        }
    }

    private static void RunManualTakeover(
        LiveScenarioResult result,
        InputSafetyGuard guard,
        IRawInputBackend raw,
        ICursorBackend cursor,
        BarrierTraceSink trace,
        LiveTakeoverRecorder takeoverRecorder,
        LiveEventRecorder eventRecorder,
        int timeoutMs,
        IInputObserver observer,
        ControlledWindowHarness? harness,
        Action? promptReady = null)
    {
        long rawBefore = raw.SendCallCount;
        long cursorBefore = cursor.SetCallCount;
        InputActionOutcome? executionOutcome = null;
        Exception? executionException = null;
        var actionThread = new Thread(() =>
        {
            try
            {
                executionOutcome = guard.Execute(InputAction.WheelWithPrepare(120, 320, 260));
            }
            catch (Exception ex)
            {
                executionException = ex;
            }
        })
        {
            IsBackground = true,
            Name = "v2-2b-live-l5-execute",
        };
        actionThread.Start();

        bool reached = trace.Reached.Wait(TimeSpan.FromMilliseconds(timeoutMs));
        result.L5BarrierReady = reached;
        result.L5BarrierReadyNs = reached ? TraceClock.NowNs() : 0;
        result.ObserverBeforeWait = observer.Diagnostics();
        eventRecorder.Record(
            "L5",
            "observer_diagnostics_before_wait",
            ("barrierReady", J.N(reached)),
            ("barrierReadyNs", J.N(result.L5BarrierReadyNs)),
            ("diagnostics", ObserverDiagnosticsJson(result.ObserverBeforeWait)));

        bool physicalMouseMove = false;
        bool otherInputStopped = false;
        if (reached)
        {
            string promptReason;
            bool promptDisplayed;
            if (harness is null)
            {
                promptDisplayed = true;
                promptReason = "FAKE_PROMPT_DISPLAYED";
            }
            else
            {
                promptDisplayed = harness.DisplayPrompt("现在移动鼠标", out promptReason);
            }

            result.L5PromptDisplayed = promptDisplayed;
            result.L5PromptReason = promptReason;
            result.L5PromptNs = TraceClock.NowNs();
            eventRecorder.Record(
                "L5",
                "manual_prompt",
                ("text", J.N("现在移动鼠标")),
                ("displayed", J.N(promptDisplayed)),
                ("reason", J.N(promptReason)),
                ("promptNs", J.N(result.L5PromptNs)));

            if (promptDisplayed)
            {
                Console.WriteLine("L5: 现在移动鼠标（只移动鼠标，不点击、不键盘输入）");
                promptReady?.Invoke();
                result.L5ManualWaitStartedNs = TraceClock.NowNs();
                Stopwatch stopwatch = Stopwatch.StartNew();
                while (stopwatch.ElapsedMilliseconds < timeoutMs)
                {
                    if (takeoverRecorder.HasHardwareMouseMoveAfter(result.L5PromptNs))
                    {
                        physicalMouseMove = true;
                        break;
                    }

                    // Any other observed input is a safety stop, but it is not a
                    // valid L5 sample.  Do not reinterpret keyboard/button/
                    // injected input as proof of a physical mouse move.
                    bool observedAfterPrompt = takeoverRecorder.SnapshotEvents()
                        .Any(observed => observed.MonotonicNs >= result.L5PromptNs);
                    if (observedAfterPrompt || guard.State == GuardState.Cancelled)
                    {
                        otherInputStopped = true;
                        break;
                    }

                    Thread.Sleep(10);
                }

                result.L5ManualWaitEndedNs = TraceClock.NowNs();
            }
        }

        result.ObserverAfterWait = observer.Diagnostics();
        eventRecorder.Record(
            "L5",
            "observer_diagnostics_after_wait",
            ("diagnostics", ObserverDiagnosticsJson(result.ObserverAfterWait)));

        IReadOnlyList<ObservedInputEvent> mouseEvents = takeoverRecorder.SnapshotEvents()
            .Where(observed => observed.Device == InputDeviceClass.Mouse)
            .ToArray();
        int hardwareMouseEvents = 0;
        int injectedMouseEvents = 0;
        int lowerIntegrityMouseEvents = 0;
        foreach (ObservedInputEvent observed in mouseEvents)
        {
            if (observed.Origin == InputEventOrigin.Hardware)
            {
                hardwareMouseEvents++;
            }
            else if (observed.Origin == InputEventOrigin.Injected)
            {
                injectedMouseEvents++;
            }
            else if (observed.Origin == InputEventOrigin.LowerIntegrityInjected)
            {
                lowerIntegrityMouseEvents++;
            }

            result.L5MouseEvents.Add(MouseEventJson(observed));
        }

        eventRecorder.Record(
            "L5",
            "mouse_event_diagnostics",
            ("events", result.L5MouseEvents.DeepClone()),
            ("mouseEventCount", J.N(mouseEvents.Count)),
            ("hardwareCount", J.N(hardwareMouseEvents)),
            ("injectedCount", J.N(injectedMouseEvents)),
            ("lowerIntegrityInjectedCount", J.N(lowerIntegrityMouseEvents)));

        if (!physicalMouseMove)
        {
            guard.Cancel(
                !reached
                    ? "L5_BARRIER_TIMEOUT"
                    : !result.L5PromptDisplayed
                        ? "L5_PROMPT_DISPLAY_FAILED"
                        : "L5_OPERATOR_TIMEOUT");
        }

        if (physicalMouseMove)
        {
            // The recorder callback runs immediately before guard.OnObservedInput;
            // wait briefly for the guard's own cancellation state to linearise
            // before releasing the pre-prepare barrier.
            Stopwatch guardCancellationWait = Stopwatch.StartNew();
            while (!guard.UserTakeoverSeen && guardCancellationWait.ElapsedMilliseconds < 500)
            {
                Thread.Sleep(5);
            }

            if (!guard.UserTakeoverSeen)
            {
                otherInputStopped = true;
            }
        }

        trace.Continue.Set();
        bool threadExited = actionThread.Join(TimeSpan.FromMilliseconds(timeoutMs));
        result.RawCalls = raw.SendCallCount - rawBefore;
        result.RawBackendReached = result.RawCalls > 0;
        result.CursorSetCalls = cursor.SetCallCount - cursorBefore;
        result.ExecutionThreadExited = threadExited;
        result.ExecutionOutcomeOk = executionOutcome?.Ok ?? false;
        result.ExecutionStage = executionOutcome?.Stage ?? string.Empty;
        result.ExecutionReason = executionOutcome?.Reason ?? string.Empty;
        result.ExecutionException = executionException?.ToString() ?? string.Empty;
        result.PhysicalMouseMove = result.L5PromptNs == 0
            ? null
            : takeoverRecorder.FirstHardwareMouseMoveAfter(result.L5PromptNs);
        result.PhysicalMouseMoveObserved = result.PhysicalMouseMove is not null;
        result.ObservedEventCount = takeoverRecorder.EventCount;
        result.CancelBeforePrepare = executionOutcome is { } outcome &&
            outcome.Reason == InputSafetyReasons.Cancelled &&
            outcome.Stage == "PREPARE" &&
            !trace.Inner.Contains(TracePhase.CursorPrepareInvoked);
        result.Passed = reached && result.L5PromptDisplayed && physicalMouseMove &&
                        !otherInputStopped && threadExited &&
                        executionOutcome is { Ok: false } &&
                        result.CancelBeforePrepare &&
                        result.CursorSetCalls == 0 &&
                        result.RawCalls == 0;
        result.Reason = result.Passed
            ? "OK"
            : !reached
                ? "L5_BARRIER_TIMEOUT"
                : !result.L5PromptDisplayed
                    ? "L5_PROMPT_DISPLAY_FAILED"
                    : "L5_REQUIRES_HARDWARE_MOUSE_MOVE_AND_PREPARE_CANCEL";
        eventRecorder.Record(
            "L5",
            "manual_result",
            ("barrierReady", J.N(reached)),
            ("promptDisplayed", J.N(result.L5PromptDisplayed)),
            ("promptNs", J.N(result.L5PromptNs)),
            ("hardwareMouseMove", J.N(result.PhysicalMouseMoveObserved)),
            ("otherInputStopped", J.N(otherInputStopped)),
            ("threadExited", J.N(threadExited)),
            ("outcomeOk", J.N(result.ExecutionOutcomeOk)),
            ("stage", J.N(result.ExecutionStage)),
            ("reason", J.N(result.ExecutionReason)),
            ("exception", J.N(result.ExecutionException)),
            ("cancelBeforePrepare", J.N(result.CancelBeforePrepare)),
            ("cursorSetCalls", J.N(result.CursorSetCalls)),
            ("rawCalls", J.N(result.RawCalls)));
    }

    private static JsonNode? ObserverDiagnosticsJson(ObserverDiagnostics? diagnostics)
    {
        if (diagnostics is not { } value)
        {
            return null;
        }

        return J.Obj(
            ("name", J.N(value.Name)),
            ("hooksInstalled", J.N(value.HooksInstalled)),
            ("isRunning", J.N(value.IsRunning)),
            ("threadAlive", J.N(value.ThreadAlive)),
            ("keyboardHookReleased", J.N(value.KeyboardHookReleased)),
            ("mouseHookReleased", J.N(value.MouseHookReleased)),
            ("keyboardEvents", J.N(value.KeyboardEventsObserved)),
            ("mouseEvents", J.N(value.MouseEventsObserved)),
            ("forwardedEvents", J.N(value.ForwardedEvents)),
            ("suppressedInputEvents", J.N(value.SuppressedInputEvents)),
            ("sinkFaults", J.N(value.SinkFaults)),
            ("classificationFaults", J.N(value.ClassificationFaults)),
            ("callbackMaxUs", J.N(value.CallbackMaxUs)),
            ("callbackP95Us", J.N(value.CallbackP95Us)),
            ("lastError", J.N(value.LastError)));
    }

    private static JsonObject MouseEventJson(in ObservedInputEvent observed) => J.Obj(
        ("kind", J.N(observed.Kind.ToString())),
        ("device", J.N(observed.Device.ToString())),
        ("classification", J.N(observed.Origin.ToString())),
        ("nativeFlags", J.N((long)observed.NativeFlags)),
        ("nativeFlagsHex", J.N(J.Hex(observed.NativeFlags))),
        ("x", J.N(observed.X)),
        ("y", J.N(observed.Y)),
        ("monotonicNs", J.N(observed.MonotonicNs)),
        ("sequence", J.N(observed.Sequence)));

    private static bool EvaluateL5ProgramNonInterference(
        LiveScenarioResult result,
        CleanupReceipt receipt)
    {
        bool validHardwareTakeover = result.PhysicalMouseMove is
            { Kind: InputEventKind.MouseMove, Device: InputDeviceClass.Mouse, Origin: InputEventOrigin.Hardware };
        bool foregroundRestoreSkipped = receipt.Steps.Any(step =>
            step.Name == "foreground_preserve_user" && step.Ok && step.Skipped);
        bool lifecycleClean = receipt.Steps.Any(step =>
                step.Name == "observer_stop" && step.Ok && !step.Skipped) &&
            receipt.Steps.Any(step =>
                step.Name == "window_shutdown_and_wait" && step.Ok && !step.Skipped) &&
            receipt.Steps.Any(step =>
                step.Name == "sync_dispose" && step.Ok && !step.Skipped);

        return validHardwareTakeover &&
               result.CancelBeforePrepare &&
               result.ExecutionThreadExited &&
               result.CursorSetCalls == 0 &&
               !result.GuardCursorRestoreAttempted &&
               result.HarnessCleanupCursorSetCalls == 0 &&
               !result.HarnessCursorRestored &&
               result.RawCalls == 0 &&
               receipt.UserTakeover &&
               foregroundRestoreSkipped &&
               receipt.Passed &&
               lifecycleClean;
    }

    private static long WaitForMessage(Func<long> read, long expected, int timeoutMs)
    {
        Stopwatch stopwatch = Stopwatch.StartNew();
        long current;
        do
        {
            current = read();
            if (current >= expected)
            {
                return current;
            }

            Thread.Sleep(10);
        }
        while (stopwatch.ElapsedMilliseconds < timeoutMs);

        return current;
    }

    private static bool StopObserverAndVerify(
        Win32LowLevelInputObserver observer,
        bool started,
        out string reason,
        out ObserverDiagnostics diagnostics,
        out long elapsedMs)
    {
        reason = "OK";
        diagnostics = observer.Diagnostics();
        elapsedMs = 0;
        if (!started)
        {
            return true;
        }

        Stopwatch stopwatch = Stopwatch.StartNew();
        observer.Stop();
        elapsedMs = stopwatch.ElapsedMilliseconds;
        diagnostics = observer.Diagnostics();
        bool withinBudget = elapsedMs < ObserverStopTimeoutMs - 100;
        bool stopped = !diagnostics.ThreadAlive && !diagnostics.HooksInstalled;
        if (!withinBudget || !stopped)
        {
            reason = !withinBudget ? "OBSERVER_STOP_TIMEOUT" : "OBSERVER_THREAD_OR_HOOK_STILL_ACTIVE";
            return false;
        }

        return true;
    }

    private static void WriteCleanupEvidence(
        string repoRoot,
        string output,
        IReadOnlyList<CleanupCaseResult> cases,
        bool allPassed)
    {
        Directory.CreateDirectory(output);
        string rawPath = Path.Combine(output, "cleanup_raw.ndjson");
        string matrixPath = Path.Combine(output, "cleanup_matrix.json");
        string summaryPath = Path.Combine(output, "cleanup_summary.json");
        string markdownPath = Path.Combine(output, "cleanup_summary.md");
        string scenarioPath = Path.Combine(output, "live_scenario_matrix.json");
        string manifestPath = Path.Combine(output, "cleanup_manifest.json");

        var raw = new StringBuilder();
        foreach (CleanupCaseResult item in cases)
        {
            raw.AppendLine(item.ToJson().ToJsonString());
        }

        File.WriteAllText(rawPath, raw.ToString(), new UTF8Encoding(false));

        JsonArray caseArray = new(cases.Select(item => (JsonNode?)item.ToJson()).ToArray());
        string head = GitValue(repoRoot, "rev-parse", "HEAD");
        string branch = GitValue(repoRoot, "rev-parse", "--abbrev-ref", "HEAD");
        WriteJson(summaryPath, J.Obj(
            ("schemaVersion", J.N("v2.2b.live.cleanup.summary.v1")),
            ("phase", J.N("V2-2B controlled-window cleanup preparation")),
            ("baselineCommit", J.N(BaselineCommit)),
            ("acceptedOfflineHead", J.N(AcceptedOfflineHead)),
            ("headCommit", J.N(head)),
            ("branch", J.N(branch)),
            ("mode", J.N("fake-cleanup-only")),
            ("liveStarted", J.N(false)),
            ("realSendInputExecuted", J.N(false)),
            ("realLowLevelHookExecuted", J.N(false)),
            ("realFocusManipulationExecuted", J.N(false)),
            ("caseCount", J.N(cases.Count)),
            ("passed", J.N(cases.Count(item => item.Passed))),
            ("failed", J.N(cases.Count(item => !item.Passed))),
            ("allPassed", J.N(allPassed)),
            ("cases", caseArray)));

        var groups = new JsonArray();
        foreach (var group in cases.GroupBy(item => item.Id.StartsWith("CL", StringComparison.Ordinal) ? "cleanup" : "other"))
        {
            groups.Add(J.Obj(
                ("kind", J.N(group.Key)),
                ("caseIds", new JsonArray(group.Select(item => (JsonNode?)J.N(item.Id)).ToArray()))));
        }

        WriteJson(matrixPath, J.Obj(
            ("schemaVersion", J.N("v2.2b.live.cleanup.matrix.v1")),
            ("acceptedOfflineHead", J.N(AcceptedOfflineHead)),
            ("mode", J.N("fake-cleanup-only")),
            ("liveStarted", J.N(false)),
            ("cleanupOrder", new JsonArray(new[]
            {
                "stop_new_actions", "cursor_policy", "foreground_policy", "observer_stop",
                "window_shutdown_and_wait", "sync_dispose",
            }.Select(J.N).ToArray())),
            ("groups", groups),
            ("allPassed", J.N(allPassed))));

        WriteJson(scenarioPath, BuildScenarioMatrix(repoRoot, head, mode: "plan-and-fake-cleanup-only"));

        var markdown = new StringBuilder();
        markdown.AppendLine("# V2-2B controlled-window cleanup offline evidence");
        markdown.AppendLine();
        markdown.AppendLine($"- Accepted offline reference: `{AcceptedOfflineHead}`");
        markdown.AppendLine($"- Harness/runner head: `{head}`");
        markdown.AppendLine($"- Result: **{(allPassed ? "PASS" : "FAIL")}** ({cases.Count(item => item.Passed)}/{cases.Count} fake cleanup cases)");
        markdown.AppendLine("- Mode: fake cleanup only; no controlled window, hook, cursor API, SendInput, or physical input was started.");
        markdown.AppendLine();
        markdown.AppendLine("| ID | Result | Description | Failure reason | Order |");
        markdown.AppendLine("| --- | --- | --- | --- | --- |");
        foreach (CleanupCaseResult item in cases)
        {
            string failure = item.Receipt?.FailureReason ?? string.Empty;
            string order = item.Receipt is null ? string.Empty : string.Join(" → ", item.Receipt.Order);
            markdown.AppendLine($"| {item.Id} | {(item.Passed ? "PASS" : "FAIL")} | {item.Description} | {failure} | {order} |");
        }

        markdown.AppendLine();
        markdown.AppendLine("## Ownership and limits");
        markdown.AppendLine();
        markdown.AppendLine("- Guard performs per-operation cursor prepare/restore and the final state/takeover decision; the harness owns only the separate pre-window cursor restore on the no-takeover branch.");
        markdown.AppendLine("- Takeover branch reads and preserves the user cursor and does not restore the previous foreground.");
        markdown.AppendLine("- Barrier timeout invokes guard cancellation before prepare; delayed fake input cannot reopen the execution path.");
        markdown.AppendLine("- Foreground recovery records request/confirmation separately, waits within a bound, and stops on takeover or monitor-read failure.");
        markdown.AppendLine("- Cleanup timeout is failure; synchronization disposal is blocked while the window thread is alive.");
        markdown.AppendLine("- L6 is a fake fault-cleanup case only, not evidence of a real Win32 API failure.");
        File.WriteAllText(markdownPath, markdown.ToString(), new UTF8Encoding(false));

        WriteManifest(
            repoRoot,
            output,
            manifestPath,
            new[] { Path.GetFileName(rawPath), Path.GetFileName(matrixPath), Path.GetFileName(summaryPath), Path.GetFileName(markdownPath), Path.GetFileName(scenarioPath) },
            allPassed ? 0 : 1,
            mode: "fake-cleanup-only",
            liveStarted: false,
            realSendInputExecuted: false,
            realLowLevelHookExecuted: false,
            realFocusManipulationExecuted: false,
            successfulRawCalls: 0,
            extra: J.Obj(("caseCount", J.N(cases.Count)), ("passed", J.N(cases.Count(item => item.Passed)))));
    }

    private static void WriteLiveEvidence(
        string repoRoot,
        string output,
        IReadOnlyList<LiveScenarioResult> results,
        LiveEventRecorder eventRecorder,
        long successfulRawCalls,
        bool allPassed,
        int manualTimeoutMs,
        bool l1Only,
        bool throughL2,
        bool l5Only)
    {
        Directory.CreateDirectory(output);
        string rawPath = Path.Combine(output, "live_raw.ndjson");
        string matrixPath = Path.Combine(output, "live_matrix.json");
        string summaryPath = Path.Combine(output, "live_summary.json");
        string markdownPath = Path.Combine(output, "live_summary.md");
        string manifestPath = Path.Combine(output, "live_manifest.json");
        string head = GitValue(repoRoot, "rev-parse", "HEAD");
        string evidenceMode = l5Only
            ? "controlled-window-live-l5-diagnostic"
            : l1Only
            ? "controlled-window-live-l1-only"
            : throughL2
                ? "controlled-window-live-through-l2"
                : "controlled-window-live";
        string coverage = l5Only
            ? "L5 diagnostic only; L1-L4 were not started."
            : l1Only
            ? "L1 only; L2-L5 were not started."
            : throughL2
                ? "L1-L2 only; L3-L5 were not started."
                : "L1-L5 planned; failure stops and no retry is automatic.";
        bool completeLivePassClaimed = !l1Only && !throughL2 && !l5Only && allPassed;
        int runMaxSuccessfulRawCalls = l5Only ? 0 : throughL2 ? 1 : l1Only ? 0 : MaxSuccessfulRawCalls;
        int plannedScenarioCount = l5Only ? 1 : throughL2 ? 2 : l1Only ? 1 : 5;
        string resultLabel = !allPassed
            ? "FAIL/STOP"
            : completeLivePassClaimed
                ? "PASS"
                : "PASS-COVERAGE-LIMITED";

        File.WriteAllText(
            rawPath,
            string.Join(Environment.NewLine, eventRecorder.Snapshot().Select(item => item.ToJsonString())) + Environment.NewLine,
            new UTF8Encoding(false));
        WriteJson(
            matrixPath,
            BuildScenarioMatrix(
                repoRoot,
                head,
                mode: evidenceMode,
                manualTimeoutMs: manualTimeoutMs,
                coverage: coverage,
                executedScenarioIds: results.Select(item => item.Id).ToArray(),
                completeLivePassClaimed: completeLivePassClaimed,
                runMaxSuccessfulRawCalls: runMaxSuccessfulRawCalls,
                l5Only: l5Only));
        bool realSendInputExecuted = results.Any(result => result.RawBackendReached);
        bool realLowLevelHookExecuted = results.Any(result => result.HookStarted);
        bool realFocusManipulationExecuted = results.Any(result => result.ForegroundAcquired);
        bool liveStarted = results.Any(result => result.WindowCreated || result.HookStarted || result.RawBackendReached);
        WriteJson(summaryPath, J.Obj(
            ("schemaVersion", J.N("v2.2b.live.summary.v1")),
            ("acceptedOfflineHead", J.N(AcceptedOfflineHead)),
            ("headCommit", J.N(head)),
            ("mode", J.N(evidenceMode)),
            ("l1Only", J.N(l1Only)),
            ("throughL2", J.N(throughL2)),
            ("l5Only", J.N(l5Only)),
            ("coverage", J.N(coverage)),
            ("completeLivePassClaimed", J.N(completeLivePassClaimed)),
            ("plannedScenarioCount", J.N(plannedScenarioCount)),
            ("runMaxSuccessfulRawCalls", J.N(runMaxSuccessfulRawCalls)),
            ("stopAfterScenario", J.N(results.Count == 0 ? string.Empty : results[results.Count - 1].Id)),
            ("liveStarted", J.N(liveStarted)),
            ("realSendInputExecuted", J.N(realSendInputExecuted)),
            ("realLowLevelHookExecuted", J.N(realLowLevelHookExecuted)),
            ("realFocusManipulationExecuted", J.N(realFocusManipulationExecuted)),
            ("successfulRawCalls", J.N(successfulRawCalls)),
            ("maxSuccessfulRawCalls", J.N(MaxSuccessfulRawCalls)),
            ("allPassed", J.N(allPassed)),
            ("scenarios", new JsonArray(results.Select(item => (JsonNode?)item.ToJson()).ToArray()))));

        var markdown = new StringBuilder();
        markdown.AppendLine("# V2-2B controlled-window live evidence");
        markdown.AppendLine();
        markdown.AppendLine($"- Accepted offline reference: `{AcceptedOfflineHead}`");
        markdown.AppendLine($"- Runner head: `{head}`");
        markdown.AppendLine($"- Result: **{resultLabel}**");
        markdown.AppendLine($"- Coverage: {coverage}");
        markdown.AppendLine($"- Complete live PASS claimed: **{completeLivePassClaimed}**");
        markdown.AppendLine($"- Successful raw calls: {successfulRawCalls}/{runMaxSuccessfulRawCalls}; failure stops and no retry is automatic.");
        markdown.AppendLine($"- L5 manual wait: {manualTimeoutMs} ms; no physical event is never a PASS.");
        markdown.AppendLine();
        markdown.AppendLine("| ID | Result | Raw calls | Accepted | Window messages | Reason |");
        markdown.AppendLine("| --- | --- | ---: | ---: | ---: | --- |");
        foreach (LiveScenarioResult item in results)
        {
            markdown.AppendLine($"| {item.Id} | {(item.Passed ? "PASS" : "FAIL")} | {item.RawCalls} | {item.Accepted} | {item.WindowMessages} | {item.Reason} |");
        }

        File.WriteAllText(markdownPath, markdown.ToString(), new UTF8Encoding(false));
        WriteManifest(
            repoRoot,
            output,
            manifestPath,
            new[] { Path.GetFileName(rawPath), Path.GetFileName(matrixPath), Path.GetFileName(summaryPath), Path.GetFileName(markdownPath) },
            allPassed ? 0 : 1,
            mode: evidenceMode,
            liveStarted,
            realSendInputExecuted,
            realLowLevelHookExecuted,
            realFocusManipulationExecuted,
            successfulRawCalls,
            extra: J.Obj(
                ("scenarioCount", J.N(results.Count)),
                ("manualTimeoutMs", J.N(manualTimeoutMs)),
                ("l1Only", J.N(l1Only)),
                ("throughL2", J.N(throughL2)),
                ("l5Only", J.N(l5Only)),
                ("coverage", J.N(coverage)),
                ("completeLivePassClaimed", J.N(completeLivePassClaimed)),
                ("runMaxSuccessfulRawCalls", J.N(runMaxSuccessfulRawCalls)),
                ("stopAfterScenario", J.N(results.Count == 0 ? string.Empty : results[results.Count - 1].Id))));
    }

    private static JsonObject BuildScenarioMatrix(
        string repoRoot,
        string head,
        string mode,
        int manualTimeoutMs = DefaultManualTimeoutMs,
        string? coverage = null,
        IReadOnlyList<string>? executedScenarioIds = null,
        bool completeLivePassClaimed = false,
        int runMaxSuccessfulRawCalls = MaxSuccessfulRawCalls,
        bool l5Only = false) => J.Obj(
        ("schemaVersion", J.N("v2.2b.live.scenario-matrix.v2")),
        ("repository", J.N(repoRoot)),
        ("headCommit", J.N(head)),
        ("acceptedOfflineHead", J.N(AcceptedOfflineHead)),
        ("mode", J.N(mode)),
        ("l5Only", J.N(l5Only)),
        ("coverage", J.N(coverage ?? "not a live execution")),
        ("completeLivePassClaimed", J.N(completeLivePassClaimed)),
        ("runMaxSuccessfulRawCalls", J.N(runMaxSuccessfulRawCalls)),
        ("executedScenarioIds", new JsonArray((executedScenarioIds ?? Array.Empty<string>()).Select(J.N).ToArray())),
        ("markerTransport", MarkerTransportMetadata()),
        ("defaultInvocationStartsLive", J.N(false)),
        ("inputBudget", J.Obj(
            ("maxSuccessfulRawCalls", J.N(MaxSuccessfulRawCalls)),
            ("policy", J.N("L2 vertical once; L3 horizontal once; L4 prepared vertical once; failure stops; no retry")))),
        ("scenarios", new JsonArray(
            J.Obj(("id", J.N("L1")), ("kind", J.N("preflight-state")), ("realInput", J.N(false)), ("acceptance", J.N("arm, duplicate arm rejection, cancel, release"))),
            J.Obj(("id", J.N("L2")), ("kind", J.N("vertical-wheel")), ("realInput", J.N(true)), ("rawBudget", J.N(1)), ("acceptedExpected", J.N(1)), ("windowMessageExpected", J.N(1))),
            J.Obj(("id", J.N("L3")), ("kind", J.N("horizontal-wheel")), ("realInput", J.N(true)), ("rawBudget", J.N(1)), ("acceptedExpected", J.N(1)), ("windowMessageExpected", J.N(1))),
            J.Obj(("id", J.N("L4")), ("kind", J.N("prepared-vertical-wheel")), ("realInput", J.N(true)), ("rawBudget", J.N(1)), ("acceptedExpected", J.N(1)), ("windowMessageExpected", J.N(1)), ("cursorPoints", J.Obj(("operationBefore", J.N("A inside window")), ("prepare", J.N("B inside window; B != A")), ("guardRestore", J.N("B -> A")), ("harnessCleanupRestore", J.N("pre-window original -> final"))))),
            J.Obj(("id", J.N("L5")), ("kind", J.N("manual-takeover")), ("realInput", J.N(true)), ("syntheticInput", J.N(false)), ("physicalInputRequired", J.N(true)), ("prompt", J.N("现在移动鼠标")), ("timeoutMs", J.N(manualTimeoutMs)), ("noEventStatus", J.N("NOT_PASS")), ("takeoverCleanup", J.N("preserve cursor and foreground"))),
            J.Obj(("id", J.N("L6")), ("kind", J.N("fake-fault-cleanup")), ("realInput", J.N(false)), ("acceptance", J.N("offline fake only; not real Win32 API fault evidence"))))));

    private static void WriteManifest(
        string repoRoot,
        string output,
        string manifestPath,
        IReadOnlyList<string> expectedArtifacts,
        int exitCode,
        string mode,
        bool liveStarted,
        bool realSendInputExecuted,
        bool realLowLevelHookExecuted,
        bool realFocusManipulationExecuted,
        long successfulRawCalls,
        JsonObject extra)
    {
        var declared = new JsonArray();
        foreach (string path in Directory.GetFiles(output, "*", SearchOption.TopDirectoryOnly)
                     .Where(path => !string.Equals(path, manifestPath, StringComparison.OrdinalIgnoreCase))
                     .OrderBy(path => path, StringComparer.OrdinalIgnoreCase))
        {
            var info = new FileInfo(path);
            declared.Add(J.Obj(
                ("name", J.N(info.Name)),
                ("sizeBytes", J.N(info.Length)),
                ("sha256", J.N(Sha256(path)))));
        }

        string[] actual = Directory.GetFiles(output, "*", SearchOption.TopDirectoryOnly)
            .Where(path => !string.Equals(path, manifestPath, StringComparison.OrdinalIgnoreCase))
            .Select(Path.GetFileName)
            .Where(name => name is not null)
            .Cast<string>()
            .OrderBy(name => name, StringComparer.OrdinalIgnoreCase)
            .ToArray();
        string[] missing = expectedArtifacts.Except(actual, StringComparer.OrdinalIgnoreCase).ToArray();
        string[] unexpected = actual.Except(expectedArtifacts, StringComparer.OrdinalIgnoreCase).ToArray();

        JsonObject node = J.Obj(
            ("schemaVersion", J.N("evidence.manifest.v2")),
            ("phase", J.N("V2-2B controlled-window live runner preparation")),
            ("repository", J.N(repoRoot)),
            ("baselineCommit", J.N(BaselineCommit)),
            ("acceptedOfflineHead", J.N(AcceptedOfflineHead)),
            ("headCommit", J.N(GitValue(repoRoot, "rev-parse", "HEAD"))),
            ("branch", J.N(GitValue(repoRoot, "rev-parse", "--abbrev-ref", "HEAD"))),
            ("mode", J.N(mode)),
            ("liveStarted", J.N(liveStarted)),
            ("realSendInputExecuted", J.N(realSendInputExecuted)),
            ("realLowLevelHookExecuted", J.N(realLowLevelHookExecuted)),
            ("realFocusManipulationExecuted", J.N(realFocusManipulationExecuted)),
            ("maxSuccessfulRawCalls", J.N(MaxSuccessfulRawCalls)),
            ("successfulRawCalls", J.N(successfulRawCalls)),
            ("verifierExitCode", J.N(exitCode)),
            ("expectedArtifacts", new JsonArray(expectedArtifacts.Select(name => (JsonNode?)J.N(name)).ToArray())),
            ("declaredArtifacts", declared),
            ("missingArtifacts", new JsonArray(missing.Select(name => (JsonNode?)J.N(name)).ToArray())),
            ("unexpectedArtifacts", new JsonArray(unexpected.Select(name => (JsonNode?)J.N(name)).ToArray())),
            ("manifestGeneratedLast", J.N(true)),
            ("rawExitCodes", J.Obj(("runner", J.N(exitCode)))),
            ("backupRoot", J.N((string?)null)),
            ("backupHashManifest", J.N((string?)null)));
        foreach (var property in extra)
        {
            node[property.Key] = property.Value?.DeepClone();
        }

        WriteJson(manifestPath, node);
    }

    private static bool HasFlag(string[] args, string flag) => args.Any(arg => string.Equals(arg, flag, StringComparison.Ordinal));

    private static int ParseInt(string[] args, string flag, int fallback)
    {
        for (int i = 0; i + 1 < args.Length; i++)
        {
            if (string.Equals(args[i], flag, StringComparison.Ordinal) &&
                int.TryParse(args[i + 1], out int value) && value > 0)
            {
                return value;
            }
        }

        return fallback;
    }

    private static string ParseOutputDirectory(string[] args, string fallback)
    {
        for (int i = 0; i + 1 < args.Length; i++)
        {
            if (string.Equals(args[i], "--output", StringComparison.Ordinal))
            {
                return args[i + 1];
            }
        }

        return fallback;
    }

    private static string ParseRequiredDirectory(string[] args, string flag)
    {
        for (int i = 0; i + 1 < args.Length; i++)
        {
            if (string.Equals(args[i], flag, StringComparison.Ordinal))
            {
                if (string.IsNullOrWhiteSpace(args[i + 1]))
                {
                    throw new ArgumentException($"Missing directory after {flag}.");
                }

                return args[i + 1];
            }
        }

        throw new ArgumentException($"Missing required argument {flag}.");
    }

    private static JsonObject FindScenario(JsonObject summary, string id)
    {
        JsonArray scenarios = summary["scenarios"]?.AsArray()
            ?? throw new InvalidDataException("Live summary has no scenarios.");
        foreach (JsonNode? item in scenarios)
        {
            if (item is JsonObject scenario &&
                string.Equals(scenario["id"]?.GetValue<string>(), id, StringComparison.Ordinal))
            {
                return scenario;
            }
        }

        throw new InvalidDataException("Live summary has no scenario " + id + ".");
    }

    private static JsonObject RequiredObject(JsonObject parent, string property)
    {
        return parent[property] as JsonObject
            ?? throw new InvalidDataException($"JSON property '{property}' is not an object.");
    }

    private static string RequiredString(JsonObject parent, string property)
    {
        return parent[property]?.GetValue<string>()
            ?? throw new InvalidDataException($"JSON property '{property}' is not a string.");
    }

    private static string FindRepositoryRoot()
    {
        DirectoryInfo? directory = new(Environment.CurrentDirectory);
        while (directory is not null)
        {
            if (Directory.Exists(Path.Combine(directory.FullName, ".git")) ||
                File.Exists(Path.Combine(directory.FullName, ".git")))
            {
                return directory.FullName;
            }

            directory = directory.Parent;
        }

        return Environment.CurrentDirectory;
    }

    private static void EnsureOutputDirectoryIsEmpty(string output)
    {
        if (Directory.Exists(output) && Directory.EnumerateFileSystemEntries(output).Any())
        {
            throw new InvalidOperationException("Output directory must be empty: " + output);
        }

        Directory.CreateDirectory(output);
    }

    private static void WriteJson(string path, JsonNode node) =>
        File.WriteAllText(path, node.ToJsonString(new System.Text.Json.JsonSerializerOptions { WriteIndented = true }) + Environment.NewLine, new UTF8Encoding(false));

    private static JsonObject MarkerTransportMetadata()
    {
        const ulong probeMarker = 0xA1B2C3D4UL;
        NativeInputMethods.NativeMarkerBoundaryDiagnostics boundary =
            NativeInputMethods.InspectMarker(probeMarker);
        return J.Obj(
            ("transportBits", J.N(InputMarker.TransportBits)),
            ("processPointerBits", J.N(boundary.ProcessPointerBits)),
            ("uIntPtrBits", J.N(boundary.UIntPtrBits)),
            ("inputSizeBytes", J.N(boundary.InputSizeBytes)),
            ("mouseInputSizeBytes", J.N(boundary.MouseInputSizeBytes)),
            ("mouseInputExtraInfoOffsetBytes", J.N(boundary.MouseInputExtraInfoOffsetBytes)),
            ("msllHookStructSizeBytes", J.N(boundary.MsllHookStructSizeBytes)),
            ("msllHookStructExtraInfoOffsetBytes", J.N(boundary.MsllHookStructExtraInfoOffsetBytes)),
            ("probeMarkerHex", J.N(J.Hex(boundary.ManagedMarker))),
            ("nativeAssignedExtraInfoHex", J.N(J.Hex(boundary.NativeExtraInfo))),
            ("marshaledExtraInfoHex", J.N(J.Hex(boundary.MarshaledExtraInfo))));
    }

    private static string GitValue(string repository, params string[] arguments)
    {
        var start = new ProcessStartInfo
        {
            FileName = "git",
            WorkingDirectory = repository,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
        };
        foreach (string argument in arguments)
        {
            start.ArgumentList.Add(argument);
        }

        using Process process = Process.Start(start) ?? throw new InvalidOperationException("Could not start git");
        string value = process.StandardOutput.ReadToEnd().Trim();
        process.WaitForExit();
        return process.ExitCode == 0 ? value : "git-error:" + process.StandardError.ReadToEnd().Trim();
    }

    private static string Sha256(string path)
    {
        using FileStream stream = File.OpenRead(path);
        return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
    }
}
