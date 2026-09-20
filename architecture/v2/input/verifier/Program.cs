using System.Diagnostics;
using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization.Metadata;
using NteHost.Input;

namespace NteHost.Input.Verifier;

/// <summary>
/// Default V2-2B verifier entry point.  The default invocation and the explicit
/// --offline-cleanup mode are fake-only.  A live controlled-window runner exists
/// behind an explicit --live plus operator confirmation gate in LiveRunner.
/// </summary>
internal static class Program
{
    private const string BaselineCommit = "a9b52c6fb8db3c5f7dbfb2e80cb5a32bb4a526e9";
    private const string AcceptedAHead = "934ce47e3dec223a8046dbca35452de8774f857c";
    private const string ReviewDisposition = "B offline PASS accepted at 5ef51e0; controlled-window live pending";
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        WriteIndented = true,
        TypeInfoResolver = new DefaultJsonTypeInfoResolver(),
    };
    private static long _markerCounter;
    private static long _ticketCounter;
    private static long _observedCounter;

    private sealed record CaseSpec(
        string Id,
        string Kind,
        string Description,
        Func<CaseResult> Run);

    private interface ICaptureCounter
    {
        long CaptureCount { get; }
    }

    private sealed class ScriptedFocusProvider : IFocusSnapshotProvider, ICaptureCounter
    {
        private readonly Func<long, FocusSnapshot> _factory;
        private long _captureCount;

        public ScriptedFocusProvider(Func<long, FocusSnapshot> factory)
        {
            _factory = factory;
        }

        public long CaptureCount => Interlocked.Read(ref _captureCount);

        public FocusSnapshot Capture()
        {
            long index = Interlocked.Increment(ref _captureCount);
            return _factory(index);
        }
    }

    private sealed class ThrowingFocusProvider : IFocusSnapshotProvider, ICaptureCounter
    {
        private long _captureCount;

        public long CaptureCount => Interlocked.Read(ref _captureCount);

        public FocusSnapshot Capture()
        {
            Interlocked.Increment(ref _captureCount);
            throw new InvalidOperationException("deterministic focus provider failure");
        }
    }

    private sealed class GateTraceSink : IInputTraceSink
    {
        public GateTraceSink(string blockedPhase)
        {
            BlockedPhase = blockedPhase;
        }

        public InMemoryInputTraceSink Inner { get; } = new();

        public string BlockedPhase { get; }

        public ManualResetEventSlim Reached { get; } = new(false);

        public ManualResetEventSlim Continue { get; } = new(false);

        public void Write(string phase, string detail)
        {
            Inner.Write(phase, detail);
            if (string.Equals(phase, BlockedPhase, StringComparison.Ordinal))
            {
                Reached.Set();
                Continue.Wait(TimeSpan.FromSeconds(5));
            }
        }
    }

    private sealed class BlockingRawInputBackend : IRawInputBackend
    {
        private readonly object _gate = new();
        private readonly List<ulong> _sentExtraInfo = new();
        private long _sendCallCount;
        private long _inputsSentCount;

        public ManualResetEventSlim CallEntered { get; } = new(false);

        public ManualResetEventSlim AllowCommit { get; } = new(false);

        public ManualResetEventSlim CommitCompleted { get; } = new(false);

        public long SendCallCount => Interlocked.Read(ref _sendCallCount);

        public long InputsSentCount => Interlocked.Read(ref _inputsSentCount);

        public IReadOnlyList<ulong> SentExtraInfo
        {
            get { lock (_gate) { return _sentExtraInfo.ToArray(); } }
        }

        public uint Send(InputRecord[] inputs)
        {
            ArgumentNullException.ThrowIfNull(inputs);
            Interlocked.Increment(ref _sendCallCount);
            CallEntered.Set();

            if (!AllowCommit.Wait(TimeSpan.FromSeconds(5)))
            {
                throw new TimeoutException("blocking fake backend was not released");
            }

            Interlocked.Add(ref _inputsSentCount, inputs.Length);
            lock (_gate)
            {
                foreach (var input in inputs)
                {
                    _sentExtraInfo.Add(input.ExtraInfo);
                }
            }

            CommitCompleted.Set();
            return (uint)inputs.Length;
        }
    }

    private sealed class CustomRig
    {
        public CustomRig(BlockingRawInputBackend raw)
        {
            Raw = raw;
            Focus.SetTarget(Fixture.TargetId);
            Focus.SetForeground(Fixture.TargetId);
            Guard = new InputSafetyGuard(
                Observer,
                Focus,
                Cursor,
                Raw,
                Trace,
                TestOptions());
            Observer.Start(evt => Guard.OnObservedInput(evt));
        }

        public FakeInputObserver Observer { get; } = new();

        public FakeFocusSnapshotProvider Focus { get; } = new();

        public FakeCursorBackend Cursor { get; } = new(10, 10);

        public BlockingRawInputBackend Raw { get; }

        public InMemoryInputTraceSink Trace { get; } = new();

        public InputSafetyGuard Guard { get; }
    }

    public static int Main(string[] args)
    {
        try
        {
            if (args.Any(arg => string.Equals(arg, "--offline-cleanup", StringComparison.Ordinal)))
            {
                return LiveRunner.RunOfflineCleanup(args);
            }

            if (args.Any(arg => string.Equals(arg, "--offline-live-review", StringComparison.Ordinal)))
            {
                return LiveRunner.RunOfflineLiveReview(args);
            }

            if (args.Any(arg => string.Equals(arg, "--live", StringComparison.Ordinal)))
            {
                return LiveRunner.RunLive(args);
            }

            string outputDirectory = ParseOutputDirectory(args);
            return Run(outputDirectory);
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"V2-2B verifier infrastructure failure: {ex}");
            return 2;
        }
    }

    private static int Run(string outputDirectory)
    {
        string repoRoot = FindRepositoryRoot();
        string output = Path.GetFullPath(outputDirectory, repoRoot);
        EnsureOutputDirectoryIsEmpty(output);

        var specs = BuildCases();
        var results = new List<CaseResult>(specs.Count);
        DateTimeOffset startedAt = DateTimeOffset.UtcNow;

        foreach (var spec in specs)
        {
            results.Add(RunCase(spec));
        }

        bool allPassed = results.All(result => result.Passed);
        DateTimeOffset finishedAt = DateTimeOffset.UtcNow;
        WriteEvidence(repoRoot, output, specs, results, allPassed, startedAt, finishedAt);

        int passed = results.Count(result => result.Passed);
        Console.WriteLine($"V2-2B OFFLINE {(allPassed ? "PASS" : "FAIL")}: {passed}/{results.Count} cases");
        Console.WriteLine($"Evidence: {Path.Combine(output, "evidence_manifest.json")}");
        return allPassed ? 0 : 1;
    }

    private static List<CaseSpec> BuildCases() =>
    [
        new("S01", "state", "arm succeeds and duplicate arm is rejected", CaseArmDuplicate),
        new("S02", "state", "cancel is terminal and repeated cancel is idempotent", CaseCancelRepeat),
        new("S03", "state", "release is terminal and repeated release is idempotent", CaseReleaseRepeat),
        new("F01", "focus", "invalid snapshot is rejected at arm", CaseArmInvalidSnapshot),
        new("F02", "focus", "target identity mismatch is rejected at arm", CaseArmTargetMismatch),
        new("F03", "focus", "non-foreground target is rejected at arm", CaseArmNotForeground),
        new("F04", "focus", "provider exception is rejected at arm", CaseArmProviderException),
        new("F05", "focus", "target identity rebuild is rejected at final precheck", CaseTargetIdentityRebuild),
        new("F06", "focus", "deterministic focus leave-return epoch change is rejected", CaseFocusFlap),
        new("F07", "focus", "provider exception at final precheck is rejected", CaseFinalProviderException),
        new("G01", "send-gate", "wheel action follows precheck prepare final-precheck ticket raw backend", CaseWheelSend),
        new("G02", "send-gate", "horizontal wheel uses the same raw gate", CaseHorizontalWheelSend),
        new("G03", "send-gate", "prepare backend exception fails before raw send", CasePrepareException),
        new("G04", "send-gate", "prepare movement mismatch fails before raw send", CasePrepareMismatch),
        new("C01", "cursor", "cursor-only operation has zero SendInput but nonzero cursor effects", CaseCursorOnly),
        new("C02", "cursor", "clean prepare and release restore the original cursor", CaseCursorCleanRestore),
        new("C03", "cursor", "user takeover skips cursor restoration", CaseCursorUserTakeover),
        new("C04", "cursor", "cursor restore failure is reported separately", CaseCursorRestoreFailure),
        new("C05", "cursor", "cursor restore false is reported as failure and position is not assumed restored", CaseCursorRestoreFalse),
        new("C06", "cursor", "a no-prepare operation does not seal a later prepared operation", CaseCursorNoPrepareThenPrepare),
        new("C07", "cursor", "consecutive prepared operations each restore the saved cursor", CaseCursorConsecutivePrepare),
        new("C08", "cursor", "repeated release is idempotent after cursor preparation", CaseCursorRepeatedRelease),
        new("C09", "cursor", "takeover before prepare prevents cursor side effects", CaseCursorTakeoverBeforePrepare),
        new("L01", "ledger", "marker and origin are necessary but not sufficient for exemption", CaseLedgerMarkerOrigin),
        new("L02", "ledger", "intent TTL, one-shot replay and exemption budget are enforced", CaseLedgerTtlReplayBudget),
        new("L03", "ledger", "coordinate and keyboard events are never silently exempted", CaseLedgerCoordinateAndKey),
        new("L04", "ledger", "32-bit marker survives native construction and marshaling without widening-match", CaseMarkerNativeBoundary),
        new("T01", "ticket", "ticket failure matrix blocks the raw backend", CaseTicketFailures),
        new("T02", "ticket", "concurrent ticket consumption succeeds exactly once", CaseTicketConcurrentConsume),
        new("B01", "backend-trace", "backend exception reports call and delivery counts", CaseBackendException),
        new("B02", "backend-trace", "partial backend delivery reports the accepted count", CaseBackendPartial),
        new("B03", "backend-trace", "trace ordering and counter consistency are auditable", CaseTraceConsistency),
        new("K01", "concurrency", "independent cancel completes before final precheck", CaseCancelBeforeFinalPrecheck),
        new("K02", "concurrency", "cancel blocked behind raw commit is not claimed to revoke input", CaseCancelRawCommitRace),
    ];

    private static CaseResult RunCase(CaseSpec spec)
    {
        try
        {
            CaseResult result = spec.Run();
            if (!string.Equals(result.Id, spec.Id, StringComparison.Ordinal))
            {
                result.Check(false, $"case returned id {result.Id}, expected {spec.Id}");
            }

            return result;
        }
        catch (Exception ex)
        {
            var failure = NewCase(spec);
            failure.Check(false, $"Unhandled {ex.GetType().Name}: {ex.Message}");
            failure.Note = ex.ToString();
            return failure;
        }
    }

    private static CaseResult NewCase(CaseSpec spec, string expectedReason = "")
    {
        var result = new CaseResult(spec.Id, spec.Kind, spec.Description)
        {
            ExpectedReason = expectedReason,
        };
        return result;
    }

    private static InputSafetyOptions TestOptions(
        int selfIntentTtlMs = 250,
        int ticketTtlMs = 500,
        int cursorTolerancePx = 0,
        int maxSelfExemptions = 16) =>
        new()
        {
            SelfIntentTtlMs = selfIntentTtlMs,
            TicketTtlMs = ticketTtlMs,
            CursorMoveTolerancePx = cursorTolerancePx,
            MaxSelfExemptionsPerArming = maxSelfExemptions,
            MarkerFactory = NextMarker,
        };

    private static ulong NextMarker()
    {
        ulong suffix = (ulong)Interlocked.Increment(ref _markerCounter);
        return 0x10000000UL + suffix;
    }

    private static long NextTicketId() => Interlocked.Increment(ref _ticketCounter);

    private static long NextObservedSequence() => Interlocked.Increment(ref _observedCounter);

    private static CaseResult Finish(CaseResult result, Fixture fixture, InMemoryInputTraceSink? trace = null)
    {
        CaseResult finished = FinishCore(
            result,
            fixture.Guard,
            fixture.Cursor,
            fixture.FocusProvider,
            fixture.Raw,
            (trace ?? fixture.Trace).Records);
        fixture.Observer.Stop();
        return finished;
    }

    private static CaseResult FinishCustom(CaseResult result, CustomRig rig)
    {
        CaseResult finished = FinishCore(
            result,
            rig.Guard,
            rig.Cursor,
            rig.Focus,
            rig.Raw,
            rig.Trace.Records);
        rig.Observer.Stop();
        return finished;
    }

    private static CaseResult FinishCore(
        CaseResult result,
        InputSafetyGuard guard,
        FakeCursorBackend cursor,
        IFocusSnapshotProvider focus,
        IRawInputBackend raw,
        IReadOnlyList<TraceRecord> traces)
    {
        result.SendCallCount = raw.SendCallCount;
        result.InputsDelivered = raw.InputsSentCount;
        result.CursorSetCalls = cursor.SetCallCount;
        result.CursorRestoreReason = guard.CursorRestoreReason;
        result.FocusCaptureCount = GetCaptureCount(focus);
        result.ObservedInputCount = guard.ObservedInputCount;
        result.StateAfter = guard.State.ToString();
        result.TracePhases.Clear();
        foreach (var trace in traces)
        {
            result.TracePhases.Add(trace.Phase);
        }

        return result;
    }

    private static long GetCaptureCount(IFocusSnapshotProvider provider) => provider switch
    {
        FakeFocusSnapshotProvider fake => fake.CaptureCount,
        ICaptureCounter counter => counter.CaptureCount,
        _ => 0,
    };

    private static void CheckOutcome(
        CaseResult result,
        InputActionOutcome outcome,
        bool expectedOk,
        string expectedReason)
    {
        result.ActualReason = outcome.Reason;
        result.Stage = outcome.Stage;
        result.Check(outcome.Ok == expectedOk, $"outcome.Ok={outcome.Ok}, expected {expectedOk}");
        result.Check(
            string.Equals(outcome.Reason, expectedReason, StringComparison.Ordinal),
            $"reason={outcome.Reason}, expected {expectedReason}");
    }

    private static void CheckArm(CaseResult result, ArmOutcome outcome, bool expectedOk, string expectedReason)
    {
        result.ActualReason = outcome.Reason;
        result.Check(outcome.Ok == expectedOk, $"arm.Ok={outcome.Ok}, expected {expectedOk}");
        result.Check(
            string.Equals(outcome.Reason, expectedReason, StringComparison.Ordinal),
            $"arm reason={outcome.Reason}, expected {expectedReason}");
    }

    private static void CheckTraceOrder(CaseResult result, IReadOnlyList<TraceRecord> traces, params string[] phases)
    {
        int previous = -1;
        foreach (string phase in phases)
        {
            int current = -1;
            for (int i = 0; i < traces.Count; i++)
            {
                if (string.Equals(traces[i].Phase, phase, StringComparison.Ordinal))
                {
                    current = i;
                    break;
                }
            }

            result.Check(current > previous, $"trace phase {phase} appears after the preceding phase");
            previous = current;
        }
    }

    private static ObservedInputEvent Observed(
        InputEventKind kind,
        InputEventOrigin origin,
        ulong marker,
        int x = 0,
        int y = 0,
        long ns = 0) =>
        new(
            kind,
            kind == InputEventKind.KeyDown ? InputDeviceClass.Keyboard : InputDeviceClass.Mouse,
            origin,
            marker,
            x,
            y,
            ns == 0 ? TraceClock.NowNs() : ns,
            NextObservedSequence());

    private static SendInputTicket Ticket(
        InputSafetyGuard guard,
        string fingerprint,
        long? authorityId = null,
        long? expiresNs = null,
        ulong? marker = null) =>
        new(
            NextTicketId(),
            authorityId ?? guard.AuthorityId,
            fingerprint,
            TraceClock.NowNs(),
            expiresNs ?? long.MaxValue,
            marker ?? guard.Ledger.Marker);

    // --------------------------------------------------------------------- state

    private static CaseResult CaseArmDuplicate()
    {
        var spec = BuildCases().First(item => item.Id == "S01");
        var result = NewCase(spec, InputSafetyReasons.AlreadyArmed);
        var fixture = Fixture.Create(options: TestOptions());
        ArmOutcome first = fixture.Arm();
        ArmOutcome second = fixture.Arm();
        CheckArm(result, first, true, InputSafetyReasons.Ok);
        CheckArm(result, second, false, InputSafetyReasons.AlreadyArmed);
        result.Check(fixture.Focus.CaptureCount == 1, "duplicate arm does not recapture focus");
        return Finish(result, fixture);
    }

    private static CaseResult CaseCancelRepeat()
    {
        var spec = BuildCases().First(item => item.Id == "S02");
        var result = NewCase(spec, InputSafetyReasons.AlreadyCancelled);
        var fixture = Fixture.Create(options: TestOptions());
        CheckArm(result, fixture.Arm(), true, InputSafetyReasons.Ok);
        CancelOutcome first = fixture.Guard.Cancel("offline-cancel");
        CancelOutcome second = fixture.Guard.Cancel("offline-cancel-again");
        ArmOutcome armAfter = fixture.Arm();
        result.Check(first.Ok && first.Reason == "offline-cancel", "first cancel succeeds");
        result.Check(!second.Ok && second.AlreadyCancelled, "repeated cancel is idempotent");
        result.Check(!armAfter.Ok && armAfter.Reason == InputSafetyReasons.Cancelled, "cancel is terminal");
        result.Check(fixture.Guard.State == GuardState.Cancelled, "state is Cancelled");
        return Finish(result, fixture);
    }

    private static CaseResult CaseReleaseRepeat()
    {
        var spec = BuildCases().First(item => item.Id == "S03");
        var result = NewCase(spec, InputSafetyReasons.AlreadyReleased);
        var fixture = Fixture.Create(options: TestOptions());
        CheckArm(result, fixture.Arm(), true, InputSafetyReasons.Ok);
        ReleaseOutcome first = fixture.Guard.Release();
        ReleaseOutcome second = fixture.Guard.Release();
        ArmOutcome armAfter = fixture.Arm();
        result.Check(first.Ok && first.Reason == InputSafetyReasons.Ok, "first release succeeds");
        result.Check(second.Ok && second.AlreadyReleased && second.Reason == InputSafetyReasons.AlreadyReleased,
            "repeated release is reported idempotently");
        result.Check(!armAfter.Ok && armAfter.Reason == InputSafetyReasons.GuardReleased, "release is terminal");
        result.Check(fixture.Guard.State == GuardState.Released, "state is Released");
        return Finish(result, fixture);
    }

    // --------------------------------------------------------------------- focus

    private static CaseResult CaseArmInvalidSnapshot()
    {
        var spec = BuildCases().First(item => item.Id == "F01");
        var result = NewCase(spec, InputSafetyReasons.FocusSnapshotInvalid);
        var fixture = Fixture.Create(options: TestOptions());
        fixture.Focus.SetValid(false);
        ArmOutcome arm = fixture.Arm();
        CheckArm(result, arm, false, InputSafetyReasons.FocusSnapshotInvalid);
        result.Check(fixture.Raw.SendCallCount == 0, "arm rejection reaches no raw backend");
        return Finish(result, fixture);
    }

    private static CaseResult CaseArmTargetMismatch()
    {
        var spec = BuildCases().First(item => item.Id == "F02");
        var result = NewCase(spec, InputSafetyReasons.TargetIdMismatch);
        var fixture = Fixture.Create(options: TestOptions());
        CheckArm(result, fixture.Arm(Fixture.OtherId), false, InputSafetyReasons.TargetIdMismatch);
        result.Check(fixture.Raw.SendCallCount == 0, "target mismatch reaches no raw backend");
        return Finish(result, fixture);
    }

    private static CaseResult CaseArmNotForeground()
    {
        var spec = BuildCases().First(item => item.Id == "F03");
        var result = NewCase(spec, InputSafetyReasons.NotForeground);
        var fixture = Fixture.Create(options: TestOptions());
        fixture.Focus.SetForeground(Fixture.OtherId);
        CheckArm(result, fixture.Arm(), false, InputSafetyReasons.NotForeground);
        result.Check(fixture.Raw.SendCallCount == 0, "not-foreground arm reaches no raw backend");
        return Finish(result, fixture);
    }

    private static CaseResult CaseArmProviderException()
    {
        var spec = BuildCases().First(item => item.Id == "F04");
        var result = NewCase(spec, InputSafetyReasons.FocusSnapshotInvalid);
        var provider = new ThrowingFocusProvider();
        var fixture = Fixture.Create(options: TestOptions(), focusProvider: provider);
        CheckArm(result, fixture.Arm(), false, InputSafetyReasons.FocusSnapshotInvalid);
        result.Check(provider.CaptureCount == 1, "provider was sampled once");
        return Finish(result, fixture);
    }

    private static CaseResult CaseTargetIdentityRebuild()
    {
        var spec = BuildCases().First(item => item.Id == "F05");
        var result = NewCase(spec, InputSafetyReasons.TargetIdMismatch);
        var fixture = Fixture.Create(options: TestOptions());
        fixture.Focus.OnCapture = index =>
        {
            if (index == 3)
            {
                // The provider's opaque identity token changes on recreate. B must
                // reject it even if an integration layer later maps it to a recycled HWND.
                fixture.Focus.SetTarget(Fixture.OtherId);
            }
        };
        CheckArm(result, fixture.Arm(), true, InputSafetyReasons.Ok);
        InputActionOutcome outcome = fixture.Guard.Execute(InputAction.Wheel(120));
        CheckOutcome(result, outcome, false, InputSafetyReasons.TargetIdMismatch);
        result.Check(outcome.SendCallCount == 0, "identity rebuild is rejected before raw send");
        result.Check(fixture.Focus.CaptureCount == 3, "final precheck recaptures focus");
        return Finish(result, fixture);
    }

    private static CaseResult CaseFocusFlap()
    {
        var spec = BuildCases().First(item => item.Id == "F06");
        var result = NewCase(spec, InputSafetyReasons.FocusEpochChanged);
        var fixture = Fixture.Create(options: TestOptions());
        fixture.Focus.OnCapture = index =>
        {
            if (index == 3)
            {
                // The final sample sees the target foreground again, but the provider
                // epoch records the leave-and-return transition.
                fixture.Focus.SetForeground(Fixture.OtherId);
                fixture.Focus.SetForeground(Fixture.TargetId);
            }
        };
        CheckArm(result, fixture.Arm(), true, InputSafetyReasons.Ok);
        InputActionOutcome outcome = fixture.Guard.Execute(InputAction.Wheel(120));
        CheckOutcome(result, outcome, false, InputSafetyReasons.FocusEpochChanged);
        result.Check(outcome.SendCallCount == 0, "focus flap is rejected before raw send");
        result.Check(fixture.Focus.CaptureCount == 3, "final precheck recaptures after synthetic flap");
        return Finish(result, fixture);
    }

    private static CaseResult CaseFinalProviderException()
    {
        var spec = BuildCases().First(item => item.Id == "F07");
        var result = NewCase(spec, InputSafetyReasons.FocusSnapshotInvalid);
        var provider = new ScriptedFocusProvider(index =>
        {
            if (index == 3)
            {
                throw new InvalidOperationException("deterministic final focus failure");
            }

            return new FocusSnapshot(true, Fixture.TargetId, Fixture.TargetId, 0, index, TraceClock.NowNs());
        });
        var fixture = Fixture.Create(options: TestOptions(), focusProvider: provider);
        CheckArm(result, fixture.Arm(), true, InputSafetyReasons.Ok);
        InputActionOutcome outcome = fixture.Guard.Execute(InputAction.Wheel(120));
        CheckOutcome(result, outcome, false, InputSafetyReasons.FocusSnapshotInvalid);
        result.Check(outcome.SendCallCount == 0, "provider exception reaches no raw backend");
        result.Check(provider.CaptureCount == 3, "provider exception occurred at final precheck");
        return Finish(result, fixture);
    }

    // ------------------------------------------------------------------ send gate

    private static CaseResult CaseWheelSend()
    {
        var spec = BuildCases().First(item => item.Id == "G01");
        var result = NewCase(spec, InputSafetyReasons.Ok);
        var fixture = Fixture.Create(options: TestOptions());
        CheckArm(result, fixture.Arm(), true, InputSafetyReasons.Ok);
        InputActionOutcome outcome = fixture.Guard.Execute(InputAction.Wheel(120));
        CheckOutcome(result, outcome, true, InputSafetyReasons.Ok);
        result.Check(outcome.SendCallCount == 1, "one raw backend call was made");
        result.Check(outcome.InputsSentCount == 1, "one input record was accepted");
        result.Check(outcome.TicketIssued, "ticket was issued after final precheck");
        result.Check(fixture.Raw.SentExtraInfo.Count == 1, "raw record carries the current marker");
        result.Check(fixture.Guard.State == GuardState.Armed, "successful operation leaves the guard armed");
        CheckTraceOrder(result, fixture.Trace.Records,
            TracePhase.Precheck1Pass,
            TracePhase.PrepareBegin,
            TracePhase.PrepareDone,
            TracePhase.Precheck2Pass,
            TracePhase.TicketIssued,
            TracePhase.SendInputInvoked);
        return Finish(result, fixture);
    }

    private static CaseResult CaseHorizontalWheelSend()
    {
        var spec = BuildCases().First(item => item.Id == "G02");
        var result = NewCase(spec, InputSafetyReasons.Ok);
        var fixture = Fixture.Create(options: TestOptions());
        CheckArm(result, fixture.Arm(), true, InputSafetyReasons.Ok);
        InputActionOutcome outcome = fixture.Guard.Execute(InputAction.HorizontalWheel(-120));
        CheckOutcome(result, outcome, true, InputSafetyReasons.Ok);
        result.Check(outcome.SendCallCount == 1 && outcome.InputsSentCount == 1,
            "horizontal wheel sends exactly one accepted record");
        return Finish(result, fixture);
    }

    private static CaseResult CasePrepareException()
    {
        var spec = BuildCases().First(item => item.Id == "G03");
        var result = NewCase(spec, InputSafetyReasons.BackendError);
        var fixture = Fixture.Create(options: TestOptions());
        fixture.Cursor.ThrowOnSet = true;
        CheckArm(result, fixture.Arm(), true, InputSafetyReasons.Ok);
        InputActionOutcome outcome = fixture.Guard.Execute(InputAction.WheelWithPrepare(120, 50, 60));
        CheckOutcome(result, outcome, false, InputSafetyReasons.BackendError);
        result.Check(outcome.SendCallCount == 0, "prepare exception reaches no raw backend");
        result.Check(fixture.Guard.State == GuardState.Cancelled, "prepare exception fail-closes the guard");
        return Finish(result, fixture);
    }

    private static CaseResult CasePrepareMismatch()
    {
        var spec = BuildCases().First(item => item.Id == "G04");
        var result = NewCase(spec, InputSafetyReasons.CursorMoveNotApplied);
        var fixture = Fixture.Create(options: TestOptions());
        fixture.Cursor.IgnoreSet = true;
        CheckArm(result, fixture.Arm(), true, InputSafetyReasons.Ok);
        InputActionOutcome outcome = fixture.Guard.Execute(InputAction.WheelWithPrepare(120, 50, 60));
        CheckOutcome(result, outcome, false, InputSafetyReasons.CursorMoveNotApplied);
        result.Check(outcome.SendCallCount == 0, "prepare mismatch reaches no raw backend");
        result.Check(fixture.Cursor.SetCallCount == 1, "prepare attempted one cursor operation");
        return Finish(result, fixture);
    }

    // --------------------------------------------------------------------- cursor

    private static CaseResult CaseCursorOnly()
    {
        var spec = BuildCases().First(item => item.Id == "C01");
        var result = NewCase(spec, InputSafetyReasons.Ok);
        var fixture = Fixture.Create(options: TestOptions());
        CheckArm(result, fixture.Arm(), true, InputSafetyReasons.Ok);
        InputActionOutcome outcome = fixture.Guard.Execute(InputAction.MoveTo(50, 60));
        CheckOutcome(result, outcome, true, InputSafetyReasons.Ok);
        result.Check(outcome.SendCallCount == 0 && outcome.InputsSentCount == 0,
            "cursor-only action has zero SendInput");
        result.Check(fixture.Cursor.SetCallCount == 2, "cursor prepare and restore are separate effects");
        result.Check(fixture.Cursor.GetPosition() == (10, 10), "cursor restored to the saved position");
        result.Check(outcome.CursorRestoreAttempted && outcome.CursorRestored, "cursor restore succeeded");
        return Finish(result, fixture);
    }

    private static CaseResult CaseCursorCleanRestore()
    {
        var spec = BuildCases().First(item => item.Id == "C02");
        var result = NewCase(spec, InputSafetyReasons.Ok);
        var fixture = Fixture.Create(options: TestOptions());
        CheckArm(result, fixture.Arm(), true, InputSafetyReasons.Ok);
        InputActionOutcome outcome = fixture.Guard.Execute(InputAction.WheelWithPrepare(120, 50, 60));
        CheckOutcome(result, outcome, true, InputSafetyReasons.Ok);
        result.Check(outcome.SendCallCount == 1 && outcome.InputsSentCount == 1, "wheel was delivered once");
        result.Check(outcome.CursorRestoreAttempted && outcome.CursorRestored, "clean release restores cursor");
        result.Check(fixture.Cursor.GetPosition() == (10, 10), "cursor is back at its saved position");
        return Finish(result, fixture);
    }

    private static CaseResult CaseCursorUserTakeover()
    {
        var spec = BuildCases().First(item => item.Id == "C03");
        var result = NewCase(spec, InputSafetyReasons.Cancelled);
        var fixture = Fixture.Create(options: TestOptions());
        fixture.Cursor.OnSetPosition = (x, y, _) =>
            fixture.Observer.Emit(fixture.User(InputEventKind.MouseMove, x + 1, y + 1));
        CheckArm(result, fixture.Arm(), true, InputSafetyReasons.Ok);
        InputActionOutcome outcome = fixture.Guard.Execute(InputAction.WheelWithPrepare(120, 50, 60));
        CheckOutcome(result, outcome, false, InputSafetyReasons.Cancelled);
        result.Check(outcome.SendCallCount == 0, "takeover before final precheck sends nothing");
        result.Check(outcome.CursorRestoreSkipped, "cursor restore is skipped after user takeover");
        result.Check(fixture.Cursor.GetPosition() == (50, 60), "user cursor position is preserved");
        result.Check(fixture.Guard.CancelReason == InputSafetyReasons.UserMouseMove, "takeover reason is recorded");
        return Finish(result, fixture);
    }

    private static CaseResult CaseCursorRestoreFailure()
    {
        var spec = BuildCases().First(item => item.Id == "C04");
        var result = NewCase(spec, InputSafetyReasons.Ok);
        var fixture = Fixture.Create(options: TestOptions());
        fixture.Cursor.OnSetPosition = (_, _, call) =>
        {
            if (call == 1)
            {
                fixture.Cursor.ThrowOnSet = true;
            }
        };
        CheckArm(result, fixture.Arm(), true, InputSafetyReasons.Ok);
        InputActionOutcome outcome = fixture.Guard.Execute(InputAction.WheelWithPrepare(120, 50, 60));
        CheckOutcome(result, outcome, true, InputSafetyReasons.Ok);
        result.Check(outcome.SendCallCount == 1 && outcome.InputsSentCount == 1, "raw send succeeded independently");
        result.Check(outcome.CursorRestoreAttempted && !outcome.CursorRestored,
            "restore failure is recorded without rewriting send outcome");
        result.Check(outcome.CursorRestoreReason == InputSafetyReasons.CursorRestoreFailed,
            "restore failure has its own reason");
        result.Check(fixture.Cursor.SetCallCount == 2, "prepare and failed restore are counted separately");
        return Finish(result, fixture);
    }

    private static CaseResult CaseCursorRestoreFalse()
    {
        var spec = BuildCases().First(item => item.Id == "C05");
        var result = NewCase(spec, InputSafetyReasons.Ok);
        var fixture = Fixture.Create(options: TestOptions());
        fixture.Cursor.ReturnFalseOnSetCall = 2;
        CheckArm(result, fixture.Arm(), true, InputSafetyReasons.Ok);
        InputActionOutcome outcome = fixture.Guard.Execute(InputAction.WheelWithPrepare(120, 50, 60));
        CheckOutcome(result, outcome, true, InputSafetyReasons.Ok);
        result.Check(outcome.SendCallCount == 1 && outcome.InputsSentCount == 1,
            "raw send succeeds independently of a false cursor restore");
        result.Check(outcome.CursorRestoreAttempted && !outcome.CursorRestored,
            "false restore is not reported as restored");
        result.Check(outcome.CursorRestoreReason == InputSafetyReasons.CursorRestoreFailed,
            "false restore has the failure reason");
        result.Check(fixture.Cursor.GetPosition() == (50, 60),
            "fake cursor remains at the prepared position when restore returns false");
        result.Check(fixture.Cursor.SetCallCount == 2, "prepare and false restore are counted separately");
        return Finish(result, fixture);
    }

    private static CaseResult CaseCursorNoPrepareThenPrepare()
    {
        var spec = BuildCases().First(item => item.Id == "C06");
        var result = NewCase(spec, InputSafetyReasons.Ok);
        var fixture = Fixture.Create(options: TestOptions());
        CheckArm(result, fixture.Arm(), true, InputSafetyReasons.Ok);
        InputActionOutcome first = fixture.Guard.Execute(InputAction.Wheel(120));
        InputActionOutcome second = fixture.Guard.Execute(InputAction.WheelWithPrepare(120, 50, 60));
        ReleaseOutcome release = fixture.Guard.Release();
        result.Check(first.Ok && first.SendCallCount == 1, "no-prepare operation succeeds");
        result.Check(second.Ok && second.SendCallCount == 1, "later prepared operation succeeds");
        result.Check(second.CursorRestoreAttempted && second.CursorRestored,
            "later prepared operation restores its cursor");
        result.Check(fixture.Cursor.SetCallCount == 2, "only the prepared operation changes the cursor");
        result.Check(fixture.Cursor.GetPosition() == (10, 10), "later prepared operation returns to the arm position");
        result.Check(release.Ok && fixture.Guard.State == GuardState.Released,
            "release remains available after both operations");
        return Finish(result, fixture);
    }

    private static CaseResult CaseCursorConsecutivePrepare()
    {
        var spec = BuildCases().First(item => item.Id == "C07");
        var result = NewCase(spec, InputSafetyReasons.Ok);
        var fixture = Fixture.Create(options: TestOptions());
        CheckArm(result, fixture.Arm(), true, InputSafetyReasons.Ok);
        InputActionOutcome first = fixture.Guard.Execute(InputAction.WheelWithPrepare(120, 50, 60));
        InputActionOutcome second = fixture.Guard.Execute(InputAction.WheelWithPrepare(120, 70, 80));
        result.Check(first.Ok && first.CursorRestoreAttempted && first.CursorRestored,
            "first prepared operation restores independently");
        result.Check(second.Ok && second.CursorRestoreAttempted && second.CursorRestored,
            "second prepared operation restores independently");
        result.Check(fixture.Cursor.SetCallCount == 4, "two prepares and two restores are counted");
        result.Check(fixture.Cursor.GetPosition() == (10, 10), "consecutive prepared operations end at the arm position");
        result.Check(fixture.Raw.SendCallCount == 2 && fixture.Raw.InputsSentCount == 2,
            "both prepared operations reach the fake raw backend once");
        return Finish(result, fixture);
    }

    private static CaseResult CaseCursorRepeatedRelease()
    {
        var spec = BuildCases().First(item => item.Id == "C08");
        var result = NewCase(spec, InputSafetyReasons.Ok);
        var fixture = Fixture.Create(options: TestOptions());
        CheckArm(result, fixture.Arm(), true, InputSafetyReasons.Ok);
        InputActionOutcome outcome = fixture.Guard.Execute(InputAction.WheelWithPrepare(120, 50, 60));
        long callsBeforeRelease = fixture.Cursor.SetCallCount;
        ReleaseOutcome first = fixture.Guard.Release();
        long callsAfterFirstRelease = fixture.Cursor.SetCallCount;
        ReleaseOutcome second = fixture.Guard.Release();
        result.Check(outcome.Ok && outcome.CursorRestoreAttempted && outcome.CursorRestored,
            "prepared operation restores before release");
        result.Check(first.Ok && first.CursorRestoreReason == InputSafetyReasons.CursorRestoreOk,
            "first release observes the completed cursor lifecycle");
        result.Check(second.Ok && second.AlreadyReleased && second.Reason == InputSafetyReasons.AlreadyReleased,
            "repeated release remains idempotent");
        result.Check(callsBeforeRelease == callsAfterFirstRelease && fixture.Cursor.SetCallCount == callsAfterFirstRelease,
            "release does not repeat an already completed restore");
        result.Check(fixture.Cursor.GetPosition() == (10, 10), "repeated release leaves the restored position unchanged");
        return Finish(result, fixture);
    }

    private static CaseResult CaseCursorTakeoverBeforePrepare()
    {
        var spec = BuildCases().First(item => item.Id == "C09");
        var result = NewCase(spec, InputSafetyReasons.Cancelled);
        var gate = new GateTraceSink(TracePhase.Precheck1Pass);
        var fixture = Fixture.Create(options: TestOptions(), trace: gate);
        CheckArm(result, fixture.Arm(), true, InputSafetyReasons.Ok);

        InputActionOutcome? outcome = null;
        Exception? executeError = null;
        using var executeDone = new ManualResetEventSlim(false);
        var executeThread = new Thread(() =>
        {
            try
            {
                outcome = fixture.Guard.Execute(InputAction.WheelWithPrepare(120, 50, 60));
            }
            catch (Exception ex)
            {
                executeError = ex;
            }
            finally
            {
                executeDone.Set();
            }
        }) { IsBackground = true };
        executeThread.Start();

        bool reached = gate.Reached.Wait(TimeSpan.FromSeconds(5));
        result.Check(reached, "independent execution thread reached the pre-prepare barrier");

        using var takeoverReady = new ManualResetEventSlim(false);
        using var takeoverGo = new ManualResetEventSlim(false);
        using var takeoverDone = new ManualResetEventSlim(false);
        var takeoverThread = new Thread(() =>
        {
            takeoverReady.Set();
            takeoverGo.Wait(TimeSpan.FromSeconds(5));
            fixture.Cursor.ForcePosition(99, 99);
            fixture.Observer.Emit(fixture.User(InputEventKind.MouseMove, 99, 99));
            takeoverDone.Set();
        }) { IsBackground = true };
        takeoverThread.Start();
        result.Check(takeoverReady.Wait(TimeSpan.FromSeconds(5)), "independent takeover thread reached its barrier");

        if (reached)
        {
            takeoverGo.Set();
            result.Check(takeoverDone.Wait(TimeSpan.FromSeconds(5)), "takeover thread cancels before prepare is released");
            result.Check(fixture.Guard.State == GuardState.Cancelled, "user takeover is effective before prepare");
        }

        gate.Continue.Set();
        result.Check(executeDone.Wait(TimeSpan.FromSeconds(5)), "execution exits after takeover release");
        executeThread.Join(TimeSpan.FromSeconds(5));
        takeoverThread.Join(TimeSpan.FromSeconds(5));

        result.Check(executeError is null, executeError is null ? "no execution infrastructure error" : executeError.ToString());
        if (outcome is not null)
        {
            CheckOutcome(result, outcome, false, InputSafetyReasons.Cancelled);
            result.Check(outcome.SendCallCount == 0, "cancelled prepare makes zero raw calls");
            result.Check(outcome.CursorRestoreSkipped && !outcome.CursorRestoreAttempted,
                "user takeover skips cursor restore without claiming a restore");
        }
        else
        {
            result.Check(false, "cancelled prepare returned an outcome");
        }

        result.Check(fixture.Cursor.SetCallCount == 0, "cancel effective before prepare prevents SetPosition");
        result.Check(fixture.Cursor.GetPosition() == (99, 99), "user cursor position is preserved");
        result.Check(gate.Inner.Records.All(record => record.Phase != TracePhase.CursorPrepareInvoked),
            "cursor prepare commit phase is absent when cancellation wins before prepare");
        return Finish(result, fixture, gate.Inner);
    }

    // --------------------------------------------------------------------- ledger

    private static CaseResult CaseMarkerNativeBoundary()
    {
        var spec = BuildCases().First(item => item.Id == "L04");
        var result = NewCase(spec, InputSafetyReasons.DenyMarkerMismatch);
        const ulong marker = 0xA1B2C3D4UL;
        NativeInputMethods.NativeMarkerBoundaryDiagnostics boundary =
            NativeInputMethods.InspectMarker(marker);
        ulong widenedObserved = 0x00000001A1B2C3D4UL;

        result.Note = J.Obj(
            ("transportBits", J.N(InputMarker.TransportBits)),
            ("processPointerBits", J.N(boundary.ProcessPointerBits)),
            ("uIntPtrBits", J.N(boundary.UIntPtrBits)),
            ("inputSizeBytes", J.N(boundary.InputSizeBytes)),
            ("mouseInputSizeBytes", J.N(boundary.MouseInputSizeBytes)),
            ("mouseInputExtraInfoOffsetBytes", J.N(boundary.MouseInputExtraInfoOffsetBytes)),
            ("msllHookStructSizeBytes", J.N(boundary.MsllHookStructSizeBytes)),
            ("msllHookStructExtraInfoOffsetBytes", J.N(boundary.MsllHookStructExtraInfoOffsetBytes)),
            ("internalMarkerHex", J.N(J.Hex(boundary.ManagedMarker))),
            ("nativeAssignedExtraInfoHex", J.N(J.Hex(boundary.NativeExtraInfo))),
            ("marshaledExtraInfoHex", J.N(J.Hex(boundary.MarshaledExtraInfo))),
            ("widenedObservedHex", J.N(J.Hex(widenedObserved)))).ToJsonString();

        result.Check(InputMarker.IsValid(marker), "test marker is a complete non-zero 32-bit transport value");
        result.Check(boundary.ProcessPointerBits == IntPtr.Size * 8 &&
                     boundary.UIntPtrBits == UIntPtr.Size * 8,
            "process and UIntPtr widths are recorded consistently");
        result.Check(boundary.NativeExtraInfo == marker,
            "native INPUT receives the exact zero-extended transport marker");
        result.Check(boundary.MarshaledExtraInfo == marker,
            "unmanaged INPUT memory round-trips the exact transport marker");
        result.Check(boundary.MouseInputExtraInfoOffsetBytes == (IntPtr.Size == 8 ? 24 : 20),
            "MOUSEINPUT dwExtraInfo offset matches the process pointer width");
        result.Check(boundary.MsllHookStructExtraInfoOffsetBytes == (IntPtr.Size == 8 ? 24 : 20),
            "MSLLHOOKSTRUCT dwExtraInfo offset matches the process pointer width");

        long now = 4_000_000_000;
        var ledger = new SelfInjectionLedger(() => marker, () => now);
        ledger.BeginGeneration(4, 1000);
        ExemptionDecision noIntent = ledger.Evaluate(
            Observed(InputEventKind.MouseWheel, InputEventOrigin.Injected, marker, ns: now));
        ledger.Register(InputActionKind.MouseWheel, 0, 0, 0);
        ExemptionDecision exact = ledger.Evaluate(
            Observed(InputEventKind.MouseWheel, InputEventOrigin.Injected, marker, ns: now));

        ledger.BeginGeneration(4, 1000);
        ledger.Register(InputActionKind.MouseWheel, 0, 0, 0);
        ExemptionDecision widened = ledger.Evaluate(
            Observed(InputEventKind.MouseWheel, InputEventOrigin.Injected, widenedObserved, ns: now));

        result.Check(noIntent.Reason == InputSafetyReasons.DenyNoPendingIntent,
            "exact marker without intent is denied");
        result.Check(exact.Exempted, "exact 32-bit marker plus intent is exempted once");
        result.Check(widened.Reason == InputSafetyReasons.DenyMarkerMismatch,
            "a value with matching low 32 bits but non-zero high bits is denied");
        return result;
    }

    private static CaseResult CaseLedgerMarkerOrigin()
    {
        var spec = BuildCases().First(item => item.Id == "L01");
        var result = NewCase(spec);
        long now = 1_000_000_000;
        const ulong marker = 0x12345678UL;
        var ledger = new SelfInjectionLedger(() => marker, () => now);
        ledger.BeginGeneration(4, 100);

        ExemptionDecision noIntent = ledger.Evaluate(Observed(InputEventKind.MouseWheel, InputEventOrigin.Injected, marker, ns: now));
        ledger.Register(InputActionKind.MouseWheel, 0, 0, 0);
        ExemptionDecision foreign = ledger.Evaluate(Observed(InputEventKind.MouseWheel, InputEventOrigin.Injected, marker + 1, ns: now));
        ExemptionDecision hardware = ledger.Evaluate(Observed(InputEventKind.MouseWheel, InputEventOrigin.Hardware, marker, ns: now));
        ExemptionDecision lower = ledger.Evaluate(Observed(InputEventKind.MouseWheel, InputEventOrigin.LowerIntegrityInjected, marker, ns: now));
        ExemptionDecision good = ledger.Evaluate(Observed(InputEventKind.MouseWheel, InputEventOrigin.Injected, marker, ns: now));
        ExemptionDecision replay = ledger.Evaluate(Observed(InputEventKind.MouseWheel, InputEventOrigin.Injected, marker, ns: now));

        result.Check(noIntent.Reason == InputSafetyReasons.DenyNoPendingIntent, "marker alone has no pending intent");
        result.Check(foreign.Reason == InputSafetyReasons.DenyMarkerMismatch, "foreign marker is denied");
        result.Check(hardware.Reason == InputSafetyReasons.DenyNotInjected, "hardware origin is not self input");
        result.Check(lower.Reason == InputSafetyReasons.DenyLowerIntegrityInjected, "lower-integrity injection is denied");
        result.Check(good.Exempted, "matching marker plus intent grants one exemption");
        result.Check(replay.Reason == InputSafetyReasons.DenyIntentAlreadyConsumed, "replay is denied");
        return result;
    }

    private static CaseResult CaseLedgerTtlReplayBudget()
    {
        var spec = BuildCases().First(item => item.Id == "L02");
        var result = NewCase(spec);
        long now = 2_000_000_000;
        const ulong marker = 0x23456789UL;
        var ledger = new SelfInjectionLedger(() => marker, () => now);

        ledger.BeginGeneration(1, 10);
        ledger.Register(InputActionKind.MouseWheel, 0, 0, 0);
        now += 10_000_001;
        ExemptionDecision expired = ledger.Evaluate(Observed(InputEventKind.MouseWheel, InputEventOrigin.Injected, marker, ns: now));

        ledger.BeginGeneration(1, 1000);
        ledger.Register(InputActionKind.MouseWheel, 0, 0, 0);
        ledger.Register(InputActionKind.MouseWheel, 0, 0, 0);
        ExemptionDecision first = ledger.Evaluate(Observed(InputEventKind.MouseWheel, InputEventOrigin.Injected, marker, ns: now));
        ExemptionDecision budget = ledger.Evaluate(Observed(InputEventKind.MouseWheel, InputEventOrigin.Injected, marker, ns: now));

        result.Check(expired.Reason == InputSafetyReasons.DenyIntentExpired, "expired intent is denied deterministically");
        result.Check(first.Exempted, "first event consumes one budget slot");
        result.Check(budget.Reason == InputSafetyReasons.DenyBudgetExhausted, "second live intent is blocked by budget");
        result.Check(ledger.ExemptionsUsed == 1, "budget counter records one exemption");
        return result;
    }

    private static CaseResult CaseLedgerCoordinateAndKey()
    {
        var spec = BuildCases().First(item => item.Id == "L03");
        var result = NewCase(spec);
        long now = 3_000_000_000;
        const ulong marker = 0x3456789AUL;
        var ledger = new SelfInjectionLedger(() => marker, () => now);
        ledger.BeginGeneration(8, 1000);
        ledger.Register(InputActionKind.CursorMove, 10, 20, 0);
        ExemptionDecision coordinate = ledger.Evaluate(
            Observed(InputEventKind.MouseMove, InputEventOrigin.Injected, marker, 11, 20, now));

        ledger.BeginGeneration(8, 1000);
        ExemptionDecision key = ledger.Evaluate(
            Observed(InputEventKind.KeyDown, InputEventOrigin.Injected, marker, ns: now));

        ledger.BeginGeneration(8, 1000);
        ledger.Register(InputActionKind.MouseWheel, 0, 0, 0);
        ExemptionDecision action = ledger.Evaluate(
            Observed(InputEventKind.MouseHorizontalWheel, InputEventOrigin.Injected, marker, ns: now));

        result.Check(coordinate.Reason == InputSafetyReasons.DenyCoordinateMismatch,
            "cursor coordinate mismatch is denied");
        result.Check(key.Reason == InputSafetyReasons.DenyKindNeverExemptible,
            "keyboard input is never exemptible");
        result.Check(action.Reason == InputSafetyReasons.DenyNoPendingIntent,
            "action-kind mismatch is not treated as self input");
        return result;
    }

    // --------------------------------------------------------------------- ticket

    private static CaseResult CaseTicketFailures()
    {
        var spec = BuildCases().First(item => item.Id == "T01");
        var result = NewCase(spec);
        var fixture = Fixture.Create(options: TestOptions());
        CheckArm(result, fixture.Arm(), true, InputSafetyReasons.Ok);
        InputAction action = InputAction.Wheel(120);
        long now = TraceClock.NowNs();

        ExecutorOutcome missing = fixture.Guard.Executor.Execute(action, null);
        ExecutorOutcome foreign = fixture.Guard.Executor.Execute(
            action,
            Ticket(fixture.Guard, action.Fingerprint, fixture.Guard.AuthorityId + 1, long.MaxValue));
        ExecutorOutcome expired = fixture.Guard.Executor.Execute(
            action,
            Ticket(fixture.Guard, action.Fingerprint, expiresNs: now - 1));
        ExecutorOutcome mismatch = fixture.Guard.Executor.Execute(
            action,
            Ticket(fixture.Guard, InputAction.HorizontalWheel(120).Fingerprint));

        var unarmed = Fixture.Create(options: TestOptions());
        ExecutorOutcome notArmed = unarmed.Guard.Executor.Execute(
            action,
            Ticket(unarmed.Guard, action.Fingerprint));

        SendInputTicket reusable = Ticket(fixture.Guard, action.Fingerprint);
        ExecutorOutcome first = fixture.Guard.Executor.Execute(action, reusable);
        ExecutorOutcome second = fixture.Guard.Executor.Execute(action, reusable);

        result.Check(missing.Reason == InputSafetyReasons.TicketMissing && missing.SendCallCount == 0,
            "missing ticket blocks raw backend");
        result.Check(foreign.Reason == InputSafetyReasons.TicketForeign && foreign.SendCallCount == 0,
            "foreign ticket blocks raw backend");
        result.Check(expired.Reason == InputSafetyReasons.TicketExpired && expired.SendCallCount == 0,
            "expired ticket blocks raw backend");
        result.Check(mismatch.Reason == InputSafetyReasons.TicketActionMismatch && mismatch.SendCallCount == 0,
            "action-mismatched ticket blocks raw backend");
        result.Check(notArmed.Reason == InputSafetyReasons.TicketGuardNotArmed && notArmed.SendCallCount == 0,
            "unarmed guard blocks raw backend");
        result.Check(first.Ok && first.SendCallCount == 1, "valid ticket reaches raw backend once");
        result.Check(second.Reason == InputSafetyReasons.TicketReused && second.SendCallCount == 1,
            "reused ticket cannot reach raw backend again");
        result.Check(fixture.Raw.SendCallCount == 1, "ticket failures do not add raw calls");
        unarmed.Observer.Stop();
        return Finish(result, fixture);
    }

    private static CaseResult CaseTicketConcurrentConsume()
    {
        var spec = BuildCases().First(item => item.Id == "T02");
        var result = NewCase(spec);
        var fixture = Fixture.Create(options: TestOptions());
        CheckArm(result, fixture.Arm(), true, InputSafetyReasons.Ok);
        InputAction action = InputAction.Wheel(120);
        SendInputTicket ticket = Ticket(fixture.Guard, action.Fingerprint);
        using var barrier = new Barrier(2);
        var outcomes = new List<ExecutorOutcome>();
        var errors = new List<Exception>();
        object resultGate = new();

        void Run()
        {
            try
            {
                barrier.SignalAndWait(TimeSpan.FromSeconds(5));
                ExecutorOutcome outcome = fixture.Guard.Executor.Execute(action, ticket);
                lock (resultGate) { outcomes.Add(outcome); }
            }
            catch (Exception ex)
            {
                lock (resultGate) { errors.Add(ex); }
            }
        }

        var first = new Thread(Run) { IsBackground = true };
        var second = new Thread(Run) { IsBackground = true };
        first.Start();
        second.Start();
        first.Join(TimeSpan.FromSeconds(5));
        second.Join(TimeSpan.FromSeconds(5));

        result.Check(errors.Count == 0, "concurrent ticket workers completed without infrastructure errors");
        result.Check(outcomes.Count == 2, "both concurrent ticket workers returned an outcome");
        result.Check(outcomes.Count(outcome => outcome.Ok) == 1, "exactly one concurrent worker succeeded");
        result.Check(outcomes.Count(outcome => outcome.Reason == InputSafetyReasons.TicketReused) == 1,
            "exactly one concurrent worker observed ticket reuse");
        result.Check(fixture.Raw.SendCallCount == 1 && fixture.Raw.InputsSentCount == 1,
            "concurrent ticket consumption made one raw call and delivered one record");
        return Finish(result, fixture);
    }

    // --------------------------------------------------------------- backend/trace

    private static CaseResult CaseBackendException()
    {
        var spec = BuildCases().First(item => item.Id == "B01");
        var result = NewCase(spec, InputSafetyReasons.BackendError);
        var fixture = Fixture.Create(options: TestOptions());
        fixture.Raw.ThrowOnSend = true;
        CheckArm(result, fixture.Arm(), true, InputSafetyReasons.Ok);
        InputActionOutcome outcome = fixture.Guard.Execute(InputAction.Wheel(120));
        CheckOutcome(result, outcome, false, InputSafetyReasons.BackendError);
        result.Check(outcome.SendCallCount == 1, "backend exception records one raw call");
        result.Check(outcome.InputsSentCount == 0 && fixture.Raw.InputsSentCount == 0,
            "backend exception records zero accepted records");
        result.Check(fixture.Guard.State == GuardState.Cancelled, "backend exception fail-closes the guard");
        return Finish(result, fixture);
    }

    private static CaseResult CaseBackendPartial()
    {
        var spec = BuildCases().First(item => item.Id == "B02");
        var result = NewCase(spec, InputSafetyReasons.SendInputPartial);
        var fixture = Fixture.Create(options: TestOptions());
        fixture.Raw.PartialSendResult = 0;
        CheckArm(result, fixture.Arm(), true, InputSafetyReasons.Ok);
        InputActionOutcome outcome = fixture.Guard.Execute(InputAction.Wheel(120));
        CheckOutcome(result, outcome, false, InputSafetyReasons.SendInputPartial);
        result.Check(outcome.SendCallCount == 1, "partial backend records one raw call");
        result.Check(outcome.InputsSentCount == 0 && fixture.Raw.InputsSentCount == 0,
            "partial backend reports zero accepted records");
        result.Check(fixture.Guard.State == GuardState.Cancelled, "partial backend fail-closes the guard");
        return Finish(result, fixture);
    }

    private static CaseResult CaseTraceConsistency()
    {
        var spec = BuildCases().First(item => item.Id == "B03");
        var result = NewCase(spec, InputSafetyReasons.Ok);
        var fixture = Fixture.Create(options: TestOptions());
        CheckArm(result, fixture.Arm(), true, InputSafetyReasons.Ok);
        InputActionOutcome outcome = fixture.Guard.Execute(InputAction.WheelWithPrepare(120, 40, 50));
        CheckOutcome(result, outcome, true, InputSafetyReasons.Ok);
        CheckTraceOrder(result, fixture.Trace.Records,
            TracePhase.Precheck1Pass,
            TracePhase.PrepareBegin,
            TracePhase.SelfIntentRegistered,
            TracePhase.PrepareDone,
            TracePhase.Precheck2Begin,
            TracePhase.Precheck2Pass,
            TracePhase.TicketIssued,
            TracePhase.SendInputInvoked,
            TracePhase.CursorRestore);
        result.Check(outcome.SendCallCount == fixture.Raw.SendCallCount,
            "outcome send count equals raw backend call count");
        result.Check(outcome.InputsSentCount == fixture.Raw.InputsSentCount,
            "outcome accepted count equals raw backend accepted count");
        result.Check(fixture.Raw.SentExtraInfo.Count == fixture.Raw.InputsSentCount,
            "raw evidence count equals accepted record count");
        result.Check(fixture.Trace.Records.All(record => record.MonotonicNs > 0),
            "trace records carry monotonic timestamps");
        return Finish(result, fixture);
    }

    // --------------------------------------------------------------- concurrency

    private static CaseResult CaseCancelBeforeFinalPrecheck()
    {
        var spec = BuildCases().First(item => item.Id == "K01");
        var result = NewCase(spec, InputSafetyReasons.Cancelled);
        var gate = new GateTraceSink(TracePhase.Precheck1Pass);
        var fixture = Fixture.Create(options: TestOptions(), trace: gate);
        CheckArm(result, fixture.Arm(), true, InputSafetyReasons.Ok);

        InputActionOutcome? outcome = null;
        Exception? executeError = null;
        using var executeDone = new ManualResetEventSlim(false);
        var executeThread = new Thread(() =>
        {
            try
            {
                outcome = fixture.Guard.Execute(InputAction.Wheel(120));
            }
            catch (Exception ex)
            {
                executeError = ex;
            }
            finally
            {
                executeDone.Set();
            }
        }) { IsBackground = true };
        executeThread.Start();

        bool reached = gate.Reached.Wait(TimeSpan.FromSeconds(5));
        result.Check(reached, "independent execution reached the precheck barrier");

        CancelOutcome? cancel = null;
        using var cancelDone = new ManualResetEventSlim(false);
        var cancelThread = new Thread(() =>
        {
            cancel = fixture.Guard.Cancel("independent-pre-final-cancel");
            cancelDone.Set();
        }) { IsBackground = true };

        if (reached)
        {
            cancelThread.Start();
            result.Check(cancelDone.Wait(TimeSpan.FromSeconds(5)),
                "independent Cancel thread completes before final precheck");
        }

        gate.Continue.Set();
        result.Check(executeDone.Wait(TimeSpan.FromSeconds(5)), "execution thread exits after barrier release");
        executeThread.Join(TimeSpan.FromSeconds(5));
        if (cancelThread.IsAlive)
        {
            cancelThread.Join(TimeSpan.FromSeconds(5));
        }

        result.Check(executeError is null, executeError is null ? "no execution infrastructure error" : executeError.ToString());
        result.Check(cancel is { Ok: true }, "cancel linearises before final precheck");
        if (outcome is not null)
        {
            CheckOutcome(result, outcome, false, InputSafetyReasons.Cancelled);
            result.Check(outcome.SendCallCount == 0, "pre-final cancellation produces zero raw calls");
        }
        else
        {
            result.Check(false, "execution returned an outcome");
        }

        return Finish(result, fixture, gate.Inner);
    }

    private static CaseResult CaseCancelRawCommitRace()
    {
        var spec = BuildCases().First(item => item.Id == "K02");
        var result = NewCase(spec, InputSafetyReasons.Ok);
        var raw = new BlockingRawInputBackend();
        var rig = new CustomRig(raw);
        CheckArm(result, rig.Guard.Arm(new ArmRequest(Fixture.TargetId)), true, InputSafetyReasons.Ok);

        InputActionOutcome? outcome = null;
        Exception? executeError = null;
        using var executeDone = new ManualResetEventSlim(false);
        var executeThread = new Thread(() =>
        {
            try
            {
                outcome = rig.Guard.Execute(InputAction.Wheel(120));
            }
            catch (Exception ex)
            {
                executeError = ex;
            }
            finally
            {
                executeDone.Set();
            }
        }) { IsBackground = true };
        executeThread.Start();

        bool entered = raw.CallEntered.Wait(TimeSpan.FromSeconds(5));
        result.Check(entered, "raw backend entry is the observed send boundary");

        CancelOutcome? cancel = null;
        using var cancelAttempting = new ManualResetEventSlim(false);
        using var cancelGo = new ManualResetEventSlim(false);
        using var cancelDone = new ManualResetEventSlim(false);
        bool cancelStarted = false;
        var cancelThread = new Thread(() =>
        {
            cancelAttempting.Set();
            cancelGo.Wait(TimeSpan.FromSeconds(5));
            cancel = rig.Guard.Cancel("cancel-after-raw-entry");
            cancelDone.Set();
        }) { IsBackground = true };

        if (entered)
        {
            cancelThread.Start();
            cancelStarted = true;
            result.Check(cancelAttempting.Wait(TimeSpan.FromSeconds(5)), "cancel thread reached its release barrier");
            cancelGo.Set();
            bool completedBeforeCommit = cancelDone.Wait(TimeSpan.FromMilliseconds(100));
            result.Check(!completedBeforeCommit,
                "Cancel remains blocked by the state gate while raw Send is held");
            result.Check(raw.SendCallCount == 1, "raw call count records entry before commit release");
        }

        raw.AllowCommit.Set();
        result.Check(executeDone.Wait(TimeSpan.FromSeconds(5)), "execution exits after raw commit release");
        if (cancelStarted)
        {
            result.Check(cancelDone.Wait(TimeSpan.FromSeconds(5)), "blocked Cancel completes after execution releases the gate");
        }
        else
        {
            result.Check(false, "cancel thread was started after observing raw backend entry");
        }
        executeThread.Join(TimeSpan.FromSeconds(5));
        if (cancelStarted)
        {
            cancelThread.Join(TimeSpan.FromSeconds(5));
        }

        result.Check(executeError is null, executeError is null ? "no execution infrastructure error" : executeError.ToString());
        result.Check(cancel is { Ok: true }, "cancel eventually takes effect");
        result.Check(raw.CommitCompleted.IsSet, "fake backend accepted the record before cancel linearised");
        if (outcome is not null)
        {
            CheckOutcome(result, outcome, true, InputSafetyReasons.Ok);
            result.Check(outcome.SendCallCount == 1 && outcome.InputsSentCount == 1,
                "already-entered send is reported as one call and one accepted record");
        }
        else
        {
            result.Check(false, "execution returned an outcome");
        }

        result.Note = "SendInput commit boundary is the raw backend call; Cancel blocked behind _stateGate linearises after the accepted record and does not claim to revoke it.";
        return FinishCustom(result, rig);
    }

    // --------------------------------------------------------------- evidence I/O

    private static void WriteEvidence(
        string repoRoot,
        string output,
        IReadOnlyList<CaseSpec> specs,
        IReadOnlyList<CaseResult> results,
        bool allPassed,
        DateTimeOffset startedAt,
        DateTimeOffset finishedAt)
    {
        Directory.CreateDirectory(output);
        string rawPath = Path.Combine(output, "v2_2b_offline_raw.ndjson");
        string matrixPath = Path.Combine(output, "acceptance_matrix.json");
        string summaryPath = Path.Combine(output, "v2_2b_offline_summary.json");
        string markdownPath = Path.Combine(output, "V2_2B_Input_Guard_Offline_Summary.md");
        string environmentPath = Path.Combine(output, "environment_facts.json");
        string manifestPath = Path.Combine(output, "evidence_manifest.json");

        var raw = new StringBuilder();
        raw.AppendLine(J.Obj(
            ("schemaVersion", J.N("v2.2b.offline.raw.v1")),
            ("reviewDisposition", J.N(ReviewDisposition)),
            ("overallBPassClaimed", J.N(false)),
            ("mode", J.N("fake-backend-only")),
            ("markerTransport", MarkerTransportMetadata()),
            ("realSendInputExecuted", J.N(false)),
            ("realLowLevelHookExecuted", J.N(false)),
            ("realFocusManipulationExecuted", J.N(false)),
            ("acceptedAHead", J.N(AcceptedAHead))).ToJsonString());
        foreach (CaseResult result in results)
        {
            raw.AppendLine(result.ToJson().ToJsonString());
        }

        File.WriteAllText(rawPath, raw.ToString(), new UTF8Encoding(false));

        JsonArray caseArray = new();
        foreach (CaseResult result in results)
        {
            caseArray.Add(result.ToJson());
        }

        var summary = J.Obj(
            ("schemaVersion", J.N("v2.2b.offline.summary.v1")),
            ("phase", J.N("V2-2B Input Guard offline closure")),
            ("repository", J.N(repoRoot)),
            ("baselineCommit", J.N(BaselineCommit)),
            ("headCommit", J.N(GitValue(repoRoot, "rev-parse", "HEAD"))),
            ("branch", J.N(GitValue(repoRoot, "rev-parse", "--abbrev-ref", "HEAD"))),
            ("acceptedAHead", J.N(AcceptedAHead)),
            ("reviewDisposition", J.N(ReviewDisposition)),
            ("overallBPassClaimed", J.N(false)),
            ("startedAtUtc", J.N(startedAt.ToString("O"))),
            ("finishedAtUtc", J.N(finishedAt.ToString("O"))),
            ("mode", J.N("fake-backend-only")),
            ("markerTransport", MarkerTransportMetadata()),
            ("realSendInputExecuted", J.N(false)),
            ("realLowLevelHookExecuted", J.N(false)),
            ("realFocusManipulationExecuted", J.N(false)),
            ("caseCount", J.N(results.Count)),
            ("passed", J.N(results.Count(result => result.Passed))),
            ("failed", J.N(results.Count(result => !result.Passed))),
            ("allPassed", J.N(allPassed)),
            ("cases", caseArray));
        WriteJson(summaryPath, summary);

        JsonArray groups = new();
        foreach (var group in specs.GroupBy(spec => spec.Kind))
        {
            var caseIds = new JsonArray();
            foreach (CaseSpec spec in group)
            {
                caseIds.Add(spec.Id);
            }

            groups.Add(J.Obj(
                ("kind", J.N(group.Key)),
                ("requirement", J.N(GroupRequirement(group.Key))),
                ("caseIds", caseIds)));
        }

        WriteJson(matrixPath, J.Obj(
            ("schemaVersion", J.N("v2.2b.offline.matrix.v1")),
            ("contract", J.N("V2-2B offline closure current task contract")),
            ("reviewDisposition", J.N(ReviewDisposition)),
            ("overallBPassClaimed", J.N(false)),
            ("countsAreReviewSurface", J.N(true)),
            ("markerTransport", MarkerTransportMetadata()),
            ("groups", groups),
            ("caseCount", J.N(results.Count)),
            ("allPassed", J.N(allPassed))));

        var environment = J.Obj(
            ("schemaVersion", J.N("v2.2b.offline.environment.v1")),
            ("repository", J.N(repoRoot)),
            ("baselineCommit", J.N(BaselineCommit)),
            ("headCommit", J.N(GitValue(repoRoot, "rev-parse", "HEAD"))),
            ("branch", J.N(GitValue(repoRoot, "rev-parse", "--abbrev-ref", "HEAD"))),
            ("gitStatus", J.N(GitValue(repoRoot, "status", "--short", "--branch"))),
            ("acceptedAHead", J.N(AcceptedAHead)),
            ("reviewDisposition", J.N(ReviewDisposition)),
            ("overallBPassClaimed", J.N(false)),
            ("mode", J.N("fake-backend-only")),
            ("markerTransport", MarkerTransportMetadata()),
            ("realSendInputExecuted", J.N(false)),
            ("realLowLevelHookExecuted", J.N(false)),
            ("realFocusManipulationExecuted", J.N(false)),
            ("productionReachable", J.N(false)),
            ("bridgeAdded", J.N(false)),
            ("backupRoot", J.N("D:\\v2-2b-input-backup-20260919-01")),
            ("backupHashManifest", J.N("D:\\v2-2b-input-backup-20260919-01\\input-files.sha256")));
        WriteJson(environmentPath, environment);

        var markdown = new StringBuilder();
        markdown.AppendLine("# V2-2B Input Guard Offline Summary");
        markdown.AppendLine();
        markdown.AppendLine($"- Baseline: `{BaselineCommit}`");
        markdown.AppendLine($"- Head: `{GitValue(repoRoot, "rev-parse", "HEAD")}`");
        markdown.AppendLine($"- Branch: `{GitValue(repoRoot, "rev-parse", "--abbrev-ref", "HEAD")}`");
        markdown.AppendLine($"- Result: **{(allPassed ? "PASS" : "FAIL")}** ({results.Count(result => result.Passed)}/{results.Count} cases)");
        markdown.AppendLine($"- Review disposition: **{ReviewDisposition}**; this evidence does not claim overall B PASS.");
        markdown.AppendLine("- Mode: fake backend only; no real `SendInput`, low-level hook, foreground manipulation, bridge, or production path.");
        markdown.AppendLine($"- Accepted A reference: `{AcceptedAHead}`; no A tests were rerun.");
        markdown.AppendLine();
        markdown.AppendLine("## Acceptance matrix");
        markdown.AppendLine();
        markdown.AppendLine("| ID | Group | Result | Send calls | Inputs delivered | State | Description |");
        markdown.AppendLine("| --- | --- | --- | ---: | ---: | --- | --- |");
        foreach (CaseSpec spec in specs)
        {
            CaseResult result = results.First(item => item.Id == spec.Id);
            markdown.AppendLine($"| {result.Id} | {result.Kind} | {(result.Passed ? "PASS" : "FAIL")} | {result.SendCallCount} | {result.InputsDelivered} | {result.StateAfter} | {result.Description} |");
        }

        markdown.AppendLine();
        markdown.AppendLine("## Known limits");
        markdown.AppendLine();
        markdown.AppendLine("- Full desktop focus flap, A/B adapter, epoch production, event lag/loss/overflow and snapshot/event linearization remain Integration scope.");
        markdown.AppendLine("- Controlled-window live verification remains after offline external review.");
        markdown.AppendLine("- A's `Generation` is not used as B's focus epoch.");
        markdown.AppendLine("- The raw backend commit race is tested with an independent thread and barrier; cancellation does not revoke an already-entered backend call.");
        File.WriteAllText(markdownPath, markdown.ToString(), new UTF8Encoding(false));

        string[] expectedArtifacts =
        [
            Path.GetFileName(rawPath),
            Path.GetFileName(matrixPath),
            Path.GetFileName(summaryPath),
            Path.GetFileName(markdownPath),
            Path.GetFileName(environmentPath),
        ];

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

        JsonArray sourceInventory = new();
        string inputRoot = Path.Combine(repoRoot, "architecture", "v2", "input");
        foreach (string path in Directory.GetFiles(inputRoot, "*", SearchOption.AllDirectories)
                     .Where(IsAuthoredSource)
                     .OrderBy(path => path, StringComparer.OrdinalIgnoreCase))
        {
            var info = new FileInfo(path);
            sourceInventory.Add(J.Obj(
                ("name", J.N(Path.GetRelativePath(inputRoot, path).Replace('\\', '/'))),
                ("sizeBytes", J.N(info.Length)),
                ("sha256", J.N(Sha256(path)))));
        }

        string[] actualArtifacts = Directory.GetFiles(output, "*", SearchOption.TopDirectoryOnly)
            .Where(path => !string.Equals(path, manifestPath, StringComparison.OrdinalIgnoreCase))
            .Select(Path.GetFileName)
            .Where(name => name is not null)
            .Cast<string>()
            .OrderBy(name => name, StringComparer.OrdinalIgnoreCase)
            .ToArray();
        string[] missing = expectedArtifacts.Except(actualArtifacts, StringComparer.OrdinalIgnoreCase).ToArray();
        string[] unexpected = actualArtifacts.Except(expectedArtifacts, StringComparer.OrdinalIgnoreCase).ToArray();

        WriteJson(manifestPath, J.Obj(
            ("schemaVersion", J.N("evidence.manifest.v1")),
            ("phase", J.N("V2-2B Input Guard offline closure")),
            ("repository", J.N(repoRoot)),
            ("baselineCommit", J.N(BaselineCommit)),
            ("headCommit", J.N(GitValue(repoRoot, "rev-parse", "HEAD"))),
            ("branch", J.N(GitValue(repoRoot, "rev-parse", "--abbrev-ref", "HEAD"))),
            ("acceptedAHead", J.N(AcceptedAHead)),
            ("reviewDisposition", J.N(ReviewDisposition)),
            ("overallBPassClaimed", J.N(false)),
            ("mode", J.N("fake-backend-only")),
            ("realSendInputExecuted", J.N(false)),
            ("realLowLevelHookExecuted", J.N(false)),
            ("realFocusManipulationExecuted", J.N(false)),
            ("bridgeAdded", J.N(false)),
            ("productionReachable", J.N(false)),
            ("markerTransport", MarkerTransportMetadata()),
            ("verifierExitCode", J.N(allPassed ? 0 : 1)),
            ("caseCount", J.N(results.Count)),
            ("passed", J.N(results.Count(result => result.Passed))),
            ("failed", J.N(results.Count(result => !result.Passed))),
            ("allPassed", J.N(allPassed)),
            ("expectedArtifacts", new JsonArray(expectedArtifacts.Select(name => (JsonNode?)J.N(name)).ToArray())),
            ("declaredArtifacts", declared),
            ("missingArtifacts", new JsonArray(missing.Select(name => (JsonNode?)J.N(name)).ToArray())),
            ("unexpectedArtifacts", new JsonArray(unexpected.Select(name => (JsonNode?)J.N(name)).ToArray())),
            ("sourceInventory", sourceInventory),
            ("backupRoot", J.N("D:\\v2-2b-input-backup-20260919-01")),
            ("backupHashManifest", J.N("D:\\v2-2b-input-backup-20260919-01\\input-files.sha256")),
            ("manifestGeneratedLast", J.N(true)),
            ("rawExitCodes", J.Obj(("verifier", J.N(allPassed ? 0 : 1))))));
    }

    private static string GroupRequirement(string kind) => kind switch
    {
        "state" => "arm, cancel, release and repeated operations",
        "focus" => "snapshot validity, identity, focus and epoch gates",
        "send-gate" => "precheck, prepare, final precheck, ticket and raw backend gate",
        "cursor" => "cursor side effects and restore policy separate from SendInput",
        "ledger" => "self versus user input classification and bounded exemption",
        "ticket" => "ticket failure and concurrent single consumption",
        "backend-trace" => "backend errors, partial delivery and trace/counter consistency",
        "concurrency" => "independent cancellation barriers and raw commit linearization",
        _ => "offline acceptance group",
    };

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

    private static bool IsAuthoredSource(string path)
    {
        string extension = Path.GetExtension(path);
        if (!string.Equals(extension, ".cs", StringComparison.OrdinalIgnoreCase) &&
            !string.Equals(extension, ".csproj", StringComparison.OrdinalIgnoreCase))
        {
            return false;
        }

        string normalized = path.Replace(Path.DirectorySeparatorChar, '/');
        return !normalized.Contains("/bin/", StringComparison.OrdinalIgnoreCase) &&
               !normalized.Contains("/obj/", StringComparison.OrdinalIgnoreCase);
    }

    private static void WriteJson(string path, JsonNode node)
    {
        File.WriteAllText(path, node.ToJsonString(JsonOptions) + Environment.NewLine, new UTF8Encoding(false));
    }

    private static string Sha256(string path)
    {
        using FileStream stream = File.OpenRead(path);
        byte[] digest = SHA256.HashData(stream);
        return Convert.ToHexString(digest).ToLowerInvariant();
    }

    private static string ParseOutputDirectory(string[] args)
    {
        for (int i = 0; i < args.Length; i++)
        {
            if (string.Equals(args[i], "--output", StringComparison.Ordinal) && i + 1 < args.Length)
            {
                return args[++i];
            }
        }

        return Path.Combine("build", "v2-2b-offline", "evidence");
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
        if (!Directory.Exists(output))
        {
            return;
        }

        string[] existing = Directory.GetFiles(output, "*", SearchOption.AllDirectories);
        if (existing.Length != 0)
        {
            throw new InvalidOperationException($"Evidence output directory is not empty: {output}");
        }
    }

    private static string GitValue(string repoRoot, params string[] arguments)
    {
        var startInfo = new ProcessStartInfo
        {
            FileName = "git",
            WorkingDirectory = repoRoot,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
        };
        foreach (string argument in arguments)
        {
            startInfo.ArgumentList.Add(argument);
        }

        using var process = Process.Start(startInfo);
        if (process is null)
        {
            return "UNAVAILABLE";
        }

        string output = process.StandardOutput.ReadToEnd();
        process.WaitForExit();
        return process.ExitCode == 0 ? output.Trim() : "UNAVAILABLE";
    }
}
