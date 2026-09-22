using System.Text;
using System.Text.Json;
using NteHost.Freeze;
using NteHost.Input;
using NteHost.Integration;

namespace NteIntegrationVerifier;

internal static class Program
{
    private const string BaseHead = "a9b52c6fb8db3c5f7dbfb2e80cb5a32bb4a526e9";
    private const string AHead = "934ce47e3dec223a8046dbca35452de8774f857c";
    private const string BHead = "b1334c6ac11a9873030ed67e7f6418b22f69ccc0";
    private const string CHead = "878435e96034caa130c622de0ab968162d65a595";

    private sealed record AssertionRecord(
        string Name,
        bool Passed,
        object? Expected,
        object? Actual);

    private sealed record ScenarioResult(
        string Id,
        string Description,
        bool Passed,
        IReadOnlyList<AssertionRecord> Assertions,
        string Detail);

    private sealed record ScenarioExecution(
        ScenarioResult Result,
        IReadOnlyList<TraceRecord> Trace,
        IReadOnlyList<IntegrationWindowObservation> Observations);

    private sealed class RawWriter : IDisposable
    {
        private readonly StreamWriter _writer;
        private readonly JsonSerializerOptions _options = new() { WriteIndented = false };

        public RawWriter(string path)
        {
            string? directory = Path.GetDirectoryName(Path.GetFullPath(path));
            if (!string.IsNullOrEmpty(directory)) Directory.CreateDirectory(directory);
            _writer = new StreamWriter(path, false, new UTF8Encoding(false)) { AutoFlush = true };
        }

        public void Write(object value) => _writer.WriteLine(JsonSerializer.Serialize(value, _options));

        public void Dispose() => _writer.Dispose();
    }

    private sealed class CallbackTraceSink : IInputTraceSink
    {
        private readonly InMemoryInputTraceSink _inner;

        public CallbackTraceSink(InMemoryInputTraceSink inner) => _inner = inner;

        public Action<string, string>? OnWrite { get; set; }

        public void Write(string phase, string detail)
        {
            _inner.Write(phase, detail);
            OnWrite?.Invoke(phase, detail);
        }
    }

    private sealed class Rig
    {
        public FakeWindowObservationSource Source { get; }
        public FakeInputObserver Observer { get; } = new();
        public FakeCursorBackend Cursor { get; } = new(10, 10);
        public CallbackRawInputBackend Raw { get; } = new();
        public InMemoryInputTraceSink Trace { get; } = new();
        public CallbackTraceSink TraceBridge { get; }
        public IntegrationCoordinator Coordinator { get; }

        public Rig(long aGeneration = 41)
        {
            Source = new FakeWindowObservationSource(
                FakeWindowObservationSource.Identity(), aGeneration);
            TraceBridge = new CallbackTraceSink(Trace);
            Coordinator = new IntegrationCoordinator(
                Source,
                Observer,
                Cursor,
                Raw,
                TraceBridge,
                sessionGeneration: 1,
                inputOptions: new InputSafetyOptions
                {
                    MarkerFactory = () => 0x12345678UL,
                    RestoreCursorOnCleanRelease = true,
                });
        }

        public (bool Session, IntegrationArmResult Arm) Prepare()
        {
            bool session = Coordinator.StartSession();
            IntegrationArmResult arm = Coordinator.ArmCurrent();
            return (session, arm);
        }

        public ScenarioExecution Finish(ScenarioResult result)
        {
            Coordinator.Dispose();
            return new ScenarioExecution(result, Trace.Records, Source.ReadLog);
        }

        public (IReadOnlyList<TraceRecord> Trace, IReadOnlyList<IntegrationWindowObservation> Reads) Close()
        {
            Coordinator.Dispose();
            return (Trace.Records, Source.ReadLog);
        }
    }

    private static int Main(string[] args)
    {
        var options = ParseArgs(args);
        string outPath = options.GetValueOrDefault("--out", string.Empty);
        string rawPath = options.GetValueOrDefault("--raw-out", string.Empty);
        string repo = options.GetValueOrDefault("--repo", string.Empty);
        string head = options.GetValueOrDefault("--head", string.Empty);
        string branch = options.GetValueOrDefault("--branch", string.Empty);

        if (string.IsNullOrWhiteSpace(outPath) || string.IsNullOrWhiteSpace(rawPath))
        {
            Console.Error.WriteLine("--out and --raw-out are required");
            return 2;
        }

        var results = new List<ScenarioResult>();
        using var raw = new RawWriter(rawPath);
        foreach (var scenario in new (string Id, string Description, Func<ScenarioExecution> Run)[]
        {
            ("I01_happy_path_c_permission_b_final_gate", "C permission and B final gate allow one fake raw action.", I01),
            ("I02_focus_flap_leave_return_rejected", "A raw fence preserves a complete leave/return flap and B rejects the changed epoch.", I02),
            ("I03_queue_lag_fail_closed", "An unsettled source batch is not converted into a safe snapshot.", I03),
            ("I04_queue_overflow_fail_closed", "An overflow is a source-fence failure and produces zero raw calls.", I04),
            ("I05_same_hwnd_identity_rebuild_rejected", "A recycled HWND with a new process identity changes B TargetId.", I05),
            ("I06_user_takeover_freezes_c_and_cancels_b", "Hardware takeover cancels B and adds C USER_TAKEOVER before send.", I06),
            ("I07_multiple_reasons_require_independent_clear", "Two C reasons remain effective until both are cleared and rearmed.", I07),
            ("I08_old_credential_rejected_after_session_change", "A C credential from the prior session cannot recover the new session.", I08),
            ("I09_restart_resync_retires_credentials", "C resync is fail-closed and retires pre-resync credentials.", I09),
            ("I10_freeze_send_commit_competition", "Before raw submission freeze yields zero; after submission it cannot retract one raw call.", I10),
            ("I11_identity_epoch_session_scopes_separate", "A Generation, B Epoch/TargetId and C Generation remain separately observable.", I11),
            ("I12_internal_raw_revision_gap_fail_closed", "An internal raw revision gap is rejected even when the batch endpoints are monotonic.", I12),
        })
        {
            raw.Write(new { kind = "scenario_start", scenarioId = scenario.Id, description = scenario.Description });
            ScenarioExecution execution;
            try
            {
                execution = scenario.Run();
            }
            catch (Exception ex)
            {
                var failed = new ScenarioResult(
                    scenario.Id,
                    scenario.Description,
                    false,
                    new[] { new AssertionRecord("unhandled_exception", false, "no exception", ex.ToString()) },
                    "UNHANDLED_EXCEPTION");
                execution = new ScenarioExecution(failed, Array.Empty<TraceRecord>(), Array.Empty<IntegrationWindowObservation>());
            }

            foreach (var observation in execution.Observations)
            {
                raw.Write(new { kind = "a_observation_read", scenarioId = scenario.Id, observation });
            }

            foreach (var trace in execution.Trace)
            {
                raw.Write(new { kind = "b_trace", scenarioId = scenario.Id, trace });
            }

            raw.Write(new { kind = "scenario_result", scenarioId = scenario.Id, result = execution.Result });
            results.Add(execution.Result);
        }

        var payload = new
        {
            schemaVersion = "v2.2.integration.i1.offline.v1",
            phase = "V2-2_INTEGRATION_I1_OFFLINE",
            productionReachable = false,
            realInputExecuted = false,
            fakeSourceOnly = true,
            fakeObserverOnly = true,
            fakeActuatorOnly = true,
            repository = repo,
            branch,
            head,
            commonBase = BaseHead,
            sourceHeads = new { A = AHead, B = BHead, C = CHead },
            totalScenarios = results.Count,
            passedScenarios = results.Count(r => r.Passed),
            failedScenarios = results.Count(r => !r.Passed),
            allPassed = results.All(r => r.Passed),
            results,
        };

        string json = JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true });
        File.WriteAllText(outPath, json, new UTF8Encoding(false));
        Console.WriteLine(json);
        return results.All(r => r.Passed) ? 0 : 1;
    }

    private static Dictionary<string, string> ParseArgs(string[] args)
    {
        var result = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        for (int i = 0; i + 1 < args.Length; i += 2)
        {
            result[args[i]] = args[i + 1];
        }

        return result;
    }

    private static ScenarioExecution I01()
    {
        var rig = new Rig();
        var assertions = new List<AssertionRecord>();
        var prepared = rig.Prepare();
        var action = rig.Coordinator.Execute(InputAction.Wheel(120));
        Check(assertions, "session_ready", true, prepared.Session);
        Check(assertions, "arm_ok", true, prepared.Arm.Ok);
        Check(assertions, "c_permission_and_commit", true, action.CPermissionPassed && action.CCommitOccurred);
        Check(assertions, "b_final_precheck", true, action.BOutcome?.FinalPrecheckPassed == true);
        Check(assertions, "raw_send_calls", 1L, action.RawSendCallDelta);
        Check(assertions, "raw_accepted", 1L, action.RawAcceptedDelta);
        Check(assertions, "c_reasons_after", "", string.Join(',', action.ActiveFreezeReasons));
        return rig.Finish(Result("I01_happy_path_c_permission_b_final_gate", "C permission and B final gate allow one fake raw action.", assertions,
            $"raw={action.RawSendCallDelta};accepted={action.RawAcceptedDelta};cCommit={action.CCommitOccurred}"));
    }

    private static ScenarioExecution I02()
    {
        var rig = new Rig();
        var assertions = new List<AssertionRecord>();
        var prepared = rig.Prepare();
        rig.Source.AfterRead = (read, source) =>
        {
            if (read == 3)
            {
                source.SetForeground(false, "flap-lost");
                source.SetForeground(true, "flap-returned");
                source.AfterRead = null;
            }
        };
        var action = rig.Coordinator.Execute(InputAction.Wheel(120));
        Check(assertions, "arm_ok", true, prepared.Arm.Ok);
        Check(assertions, "raw_zero", 0L, action.RawSendCallDelta);
        Check(assertions, "c_focus_reason", true, action.ActiveFreezeReasons.Contains(FreezeReason.FOCUS_LOST));
        Check(assertions, "b_epoch_rejected", InputSafetyReasons.FocusEpochChanged, action.BOutcome?.Reason);
        Check(assertions, "a_events_two", 2, rig.Source.ReadLog.Sum(x => x.Events.Count));
        Check(assertions, "a_generation_not_b_epoch", true, rig.Coordinator.FocusAdapter.Last.AGeneration != rig.Coordinator.FocusAdapter.Last.FocusEpoch);
        return rig.Finish(Result("I02_focus_flap_leave_return_rejected", "A raw fence preserves a complete leave/return flap and B rejects the changed epoch.", assertions,
            $"rawRevision={rig.Coordinator.FocusAdapter.Last.SourceRevision};bEpoch={rig.Coordinator.FocusAdapter.Last.FocusEpoch}"));
    }

    private static ScenarioExecution I03()
    {
        var rig = new Rig();
        var assertions = new List<AssertionRecord>();
        var prepared = rig.Prepare();
        rig.Source.AfterRead = (read, source) =>
        {
            if (read == 3)
            {
                source.MarkPending();
                source.AfterRead = null;
            }
        };
        var action = rig.Coordinator.Execute(InputAction.Wheel(120));
        Check(assertions, "arm_ok", true, prepared.Arm.Ok);
        Check(assertions, "source_fence_broken", true, rig.Coordinator.FocusAdapter.Last.SourceFenceBroken);
        Check(assertions, "pending_reason", "SOURCE_PENDING_EVENTS", rig.Coordinator.FocusAdapter.Last.Reason);
        Check(assertions, "raw_zero", 0L, action.RawSendCallDelta);
        Check(assertions, "c_frozen", true, action.ActiveFreezeReasons.Contains(FreezeReason.FOCUS_LOST));
        return rig.Finish(Result("I03_queue_lag_fail_closed", "An unsettled source batch is not converted into a safe snapshot.", assertions, rig.Coordinator.FocusAdapter.Last.Reason));
    }

    private static ScenarioExecution I04()
    {
        var rig = new Rig();
        var assertions = new List<AssertionRecord>();
        var prepared = rig.Prepare();
        rig.Source.AfterRead = (read, source) =>
        {
            if (read == 3)
            {
                source.MarkOverflow(2);
                source.AfterRead = null;
            }
        };
        var action = rig.Coordinator.Execute(InputAction.Wheel(120));
        Check(assertions, "arm_ok", true, prepared.Arm.Ok);
        Check(assertions, "overflow_count", 2L, rig.Source.ReadLog.Last().DroppedSinceLastRead);
        Check(assertions, "raw_zero", 0L, action.RawSendCallDelta);
        Check(assertions, "c_frozen", true, action.ActiveFreezeReasons.Contains(FreezeReason.FOCUS_LOST));
        Check(assertions, "overflow_not_recovered_by_poll", true, rig.Coordinator.FocusAdapter.Last.SourceFenceBroken);
        return rig.Finish(Result("I04_queue_overflow_fail_closed", "An overflow is a source-fence failure and produces zero raw calls.", assertions, rig.Coordinator.FocusAdapter.Last.Reason));
    }

    private static ScenarioExecution I05()
    {
        var rig = new Rig();
        var assertions = new List<AssertionRecord>();
        var prepared = rig.Prepare();
        long oldTarget = prepared.Arm.TargetId;
        rig.Source.AfterRead = (read, source) =>
        {
            if (read == 3)
            {
                source.RebuildSameHwnd(101, 0xdef2, 42);
                source.AfterRead = null;
            }
        };
        var action = rig.Coordinator.Execute(InputAction.Wheel(120));
        long newTarget = rig.Coordinator.FocusAdapter.Last.TargetId;
        Check(assertions, "arm_ok", true, prepared.Arm.Ok);
        Check(assertions, "same_hwnd", 0x1001L, rig.Source.CurrentSnapshot.TargetHwnd);
        Check(assertions, "target_id_changes", true, oldTarget != newTarget);
        Check(assertions, "b_identity_rejected", InputSafetyReasons.TargetIdMismatch, action.BOutcome?.Reason);
        Check(assertions, "raw_zero", 0L, action.RawSendCallDelta);
        Check(assertions, "c_focus_reason", true, action.ActiveFreezeReasons.Contains(FreezeReason.FOCUS_LOST));
        return rig.Finish(Result("I05_same_hwnd_identity_rebuild_rejected", "A recycled HWND with a new process identity changes B TargetId.", assertions,
            $"oldTarget={oldTarget};newTarget={newTarget};raw={action.RawSendCallDelta}"));
    }

    private static ScenarioExecution I06()
    {
        var rig = new Rig();
        var assertions = new List<AssertionRecord>();
        var prepared = rig.Prepare();
        bool emitted = false;
        rig.TraceBridge.OnWrite = (phase, _) =>
        {
            if (!emitted && phase == TracePhase.Precheck1Pass)
            {
                emitted = true;
                rig.Observer.Emit(rig.Observer.Next(
                    InputEventKind.MouseMove,
                    InputEventOrigin.Hardware,
                    0,
                    99,
                    99));
            }
        };
        var action = rig.Coordinator.Execute(InputAction.Wheel(120));
        Check(assertions, "arm_ok", true, prepared.Arm.Ok);
        Check(assertions, "hardware_takeover_seen", true, rig.Coordinator.Guard.UserTakeoverSeen);
        Check(assertions, "b_cancelled_before_send", InputSafetyReasons.Cancelled, action.BOutcome?.Reason);
        Check(assertions, "c_user_takeover_reason", true, action.ActiveFreezeReasons.Contains(FreezeReason.USER_TAKEOVER));
        Check(assertions, "raw_zero", 0L, action.RawSendCallDelta);
        Check(assertions, "prepare_not_reached_send", false, action.BOutcome?.TicketIssued ?? false);
        return rig.Finish(Result("I06_user_takeover_freezes_c_and_cancels_b", "Hardware takeover cancels B and adds C USER_TAKEOVER before send.", assertions,
            $"takeover={rig.Coordinator.Guard.UserTakeoverSeen};raw={action.RawSendCallDelta}"));
    }

    private static ScenarioExecution I07()
    {
        var rig = new Rig();
        var assertions = new List<AssertionRecord>();
        var prepared = rig.Prepare();
        rig.Coordinator.FreezeAtBoundary(FreezeReason.FOCUS_LOST, "multi-focus");
        rig.Coordinator.FreezeAtBoundary(FreezeReason.USER_TAKEOVER, "multi-takeover");
        var deniedAction = rig.Coordinator.Execute(InputAction.Wheel(120));
        bool clearOne = rig.Coordinator.Freeze.ClearReason(FreezeReason.FOCUS_LOST, rig.Coordinator.Freeze.GenerationId);
        RearmOutcome oneLeft = rig.Coordinator.RearmCurrent("one-left");
        bool clearTwo = rig.Coordinator.Freeze.ClearReason(FreezeReason.USER_TAKEOVER, rig.Coordinator.Freeze.GenerationId);
        RearmOutcome allClear = rig.Coordinator.RearmCurrent("all-clear");
        Check(assertions, "arm_ok", true, prepared.Arm.Ok);
        Check(assertions, "two_reasons_block", true, deniedAction.ActiveFreezeReasons.Count == 2);
        Check(assertions, "raw_zero_while_frozen", 0L, deniedAction.RawSendCallDelta);
        Check(assertions, "only_one_clear_still_rejects", RearmOutcome.REJECTED_ACTIVE_REASONS, oneLeft);
        Check(assertions, "clear_one", true, clearOne);
        Check(assertions, "clear_two", true, clearTwo);
        Check(assertions, "all_clear_rearms", RearmOutcome.APPLIED, allClear);
        return rig.Finish(Result("I07_multiple_reasons_require_independent_clear", "Two C reasons remain effective until both are cleared and rearmed.", assertions,
            $"oneLeft={oneLeft};allClear={allClear}"));
    }

    private static ScenarioExecution I08()
    {
        var rig = new Rig();
        var assertions = new List<AssertionRecord>();
        var prepared = rig.Prepare();
        string oldToken = rig.Coordinator.Freeze.IssueRearmToken("old-session");
        rig.Coordinator.Freeze.SessionChanged(2, "new-session");
        RearmOutcome oldOutcome = rig.Coordinator.Freeze.Rearm(true, true, true, true, 2, oldToken, "old-session");
        var action = rig.Coordinator.Execute(InputAction.Wheel(120));
        Check(assertions, "arm_ok", true, prepared.Arm.Ok);
        Check(assertions, "old_credential_rejected", RearmOutcome.REJECTED_STALE_TOKEN, oldOutcome);
        Check(assertions, "new_session_unverified", true, rig.Coordinator.Freeze.ActiveReasons.Contains(FreezeReason.SESSION_UNVERIFIED));
        Check(assertions, "raw_zero", 0L, action.RawSendCallDelta);
        return rig.Finish(Result("I08_old_credential_rejected_after_session_change", "A C credential from the prior session cannot recover the new session.", assertions,
            $"oldOutcome={oldOutcome};generation={rig.Coordinator.Freeze.GenerationId}"));
    }

    private static ScenarioExecution I09()
    {
        var rig = new Rig();
        var assertions = new List<AssertionRecord>();
        var prepared = rig.Prepare();
        string token = rig.Coordinator.Freeze.IssueRearmToken("before-resync");
        long beforeRound = rig.Coordinator.Freeze.FreezeRound;
        rig.Coordinator.Freeze.SnapshotResync(false, null, null, "offline-restart");
        RearmOutcome retired = rig.Coordinator.Freeze.Rearm(true, true, true, true,
            rig.Coordinator.Freeze.GenerationId, token, "retired");
        var action = rig.Coordinator.Execute(InputAction.Wheel(120));
        Check(assertions, "arm_ok", true, prepared.Arm.Ok);
        Check(assertions, "round_advanced", true, rig.Coordinator.Freeze.FreezeRound > beforeRound);
        Check(assertions, "credential_retired", RearmOutcome.REJECTED_STALE_TOKEN, retired);
        Check(assertions, "resync_session_unverified", true, rig.Coordinator.Freeze.ActiveReasons.Contains(FreezeReason.SESSION_UNVERIFIED));
        Check(assertions, "raw_zero", 0L, action.RawSendCallDelta);
        return rig.Finish(Result("I09_restart_resync_retires_credentials", "C resync is fail-closed and retires pre-resync credentials.", assertions,
            $"round={beforeRound}->{rig.Coordinator.Freeze.FreezeRound};retired={retired}"));
    }

    private static ScenarioExecution I10()
    {
        var beforeRig = new Rig();
        var beforeAssertions = new List<AssertionRecord>();
        var beforePrepared = beforeRig.Prepare();
        using var beforeReady = new ManualResetEventSlim(false);
        using var beforeRelease = new ManualResetEventSlim(false);
        beforeRig.Coordinator.BeforeActionFenceForDiagnostics = () =>
        {
            beforeReady.Set();
            beforeRelease.Wait(TimeSpan.FromSeconds(2));
        };
        IntegrationActionResult? beforeAction = null;
        var beforeTask = Task.Run(() => beforeAction = beforeRig.Coordinator.Execute(InputAction.Wheel(120)));
        bool beforeBarrier = beforeReady.Wait(TimeSpan.FromSeconds(2));
        bool freezeBefore = beforeRig.Coordinator.FreezeAtBoundary(FreezeReason.FOCUS_LOST, "before-c-commit");
        beforeRelease.Set();
        bool beforeExited = beforeTask.Wait(TimeSpan.FromSeconds(2));
        var beforeClosed = beforeRig.Close();

        var middleRig = new Rig();
        var middlePrepared = middleRig.Prepare();
        bool middleFreezeIssued = false;
        middleRig.TraceBridge.OnWrite = (phase, _) =>
        {
            if (!middleFreezeIssued && phase == TracePhase.Precheck2Pass)
            {
                middleFreezeIssued = true;
                middleRig.Coordinator.FreezeAtBoundary(FreezeReason.FOCUS_LOST, "between-b-final-and-raw");
            }
        };
        var middleAction = middleRig.Coordinator.Execute(InputAction.Wheel(120));
        var middleClosed = middleRig.Close();

        var afterRig = new Rig();
        var afterAssertions = new List<AssertionRecord>();
        var afterPrepared = afterRig.Prepare();
        using var afterRawEntered = new ManualResetEventSlim(false);
        afterRig.Raw.BeforeAccept = () =>
        {
            afterRawEntered.Set();
            afterRig.Coordinator.FreezeAtBoundary(FreezeReason.USER_TAKEOVER, "after-raw-commit");
        };
        IntegrationActionResult? afterAction = null;
        var afterTask = Task.Run(() => afterAction = afterRig.Coordinator.Execute(InputAction.Wheel(120)));
        bool afterBarrier = afterRawEntered.Wait(TimeSpan.FromSeconds(2));
        bool afterExited = afterTask.Wait(TimeSpan.FromSeconds(2));
        var afterClosed = afterRig.Close();

        var assertions = new List<AssertionRecord>
        {
            new("before_arm_ok", beforePrepared.Arm.Ok, true, beforePrepared.Arm.Ok),
            new("before_barrier_ready", beforeBarrier, true, beforeBarrier),
            new("before_freeze_applied", freezeBefore, true, freezeBefore),
            new("before_thread_exited", beforeExited, true, beforeExited),
            new("before_raw_zero", beforeAction?.RawSendCallDelta == 0, 0L, beforeAction?.RawSendCallDelta),
            new("middle_arm_ok", middlePrepared.Arm.Ok, true, middlePrepared.Arm.Ok),
            new("middle_freeze_issued_after_b_final", middleFreezeIssued, true, middleFreezeIssued),
            new("middle_b_final_precheck_passed", middleRig.Trace.Contains(TracePhase.Precheck2Pass), true, middleRig.Trace.Contains(TracePhase.Precheck2Pass)),
            new("middle_raw_zero_at_c_arbitration", middleAction.RawSendCallDelta == 0, 0L, middleAction.RawSendCallDelta),
            new("middle_underlying_raw_not_entered", middleRig.Raw.SendCallCount == 0, 0L, middleRig.Raw.SendCallCount),
            new("after_arm_ok", afterPrepared.Arm.Ok, true, afterPrepared.Arm.Ok),
            new("after_raw_barrier_ready", afterBarrier, true, afterBarrier),
            new("after_thread_exited", afterExited, true, afterExited),
            new("after_raw_one", afterAction?.RawSendCallDelta == 1, 1L, afterAction?.RawSendCallDelta),
            new("after_accepted_one", afterAction?.RawAcceptedDelta == 1, 1L, afterAction?.RawAcceptedDelta),
            new("after_freeze_recorded", afterAction?.ActiveFreezeReasons.Contains(FreezeReason.USER_TAKEOVER) == true,
                "USER_TAKEOVER", afterAction?.ActiveFreezeReasons),
            new("after_not_retracted", afterAction?.RawSendCallDelta == 1, "submitted input remains counted", afterAction?.RawSendCallDelta),
        };
        return new ScenarioExecution(
            Result("I10_freeze_send_commit_competition", "Before raw submission freeze yields zero; after submission it cannot retract one raw call.", assertions,
                $"beforeRaw={beforeAction?.RawSendCallDelta};afterRaw={afterAction?.RawSendCallDelta}"),
            beforeClosed.Trace.Concat(middleClosed.Trace).Concat(afterClosed.Trace).ToArray(),
            beforeClosed.Reads.Concat(middleClosed.Reads).Concat(afterClosed.Reads).ToArray());
    }

    private static ScenarioExecution I11()
    {
        var rig = new Rig(41);
        var assertions = new List<AssertionRecord>();
        var prepared = rig.Prepare();
        IntegrationFocusView initial = rig.Coordinator.FocusAdapter.Last;
        rig.Source.RebuildSameHwnd(101, 0xdef2, 42);
        IntegrationFocusView rebuilt = rig.Coordinator.FocusAdapter.CaptureView();
        rig.Coordinator.Freeze.SessionChanged(9, "integration-session-restart");
        var action = rig.Coordinator.Execute(InputAction.Wheel(120));
        Check(assertions, "arm_ok", true, prepared.Arm.Ok);
        Check(assertions, "a_generation_initial", 41L, initial.AGeneration);
        Check(assertions, "a_generation_rebuilt", 42L, rebuilt.AGeneration);
        Check(assertions, "b_epoch_advanced_by_events", 2L, rebuilt.FocusEpoch);
        Check(assertions, "b_target_identity_changed", true, initial.TargetId != rebuilt.TargetId);
        Check(assertions, "c_generation_independent", 9L, rig.Coordinator.Freeze.GenerationId);
        Check(assertions, "raw_zero_after_session_restart", 0L, action.RawSendCallDelta);
        Check(assertions, "scope_fields_not_aliased", true,
            initial.AGeneration != rebuilt.FocusEpoch && rebuilt.AGeneration != rig.Coordinator.Freeze.GenerationId);
        return rig.Finish(Result("I11_identity_epoch_session_scopes_separate", "A Generation, B Epoch/TargetId and C Generation remain separately observable.", assertions,
            $"a={initial.AGeneration}->{rebuilt.AGeneration};bEpoch={initial.FocusEpoch}->{rebuilt.FocusEpoch};c={rig.Coordinator.Freeze.GenerationId}"));
    }

    private static ScenarioExecution I12()
    {
        var rig = new Rig();
        var assertions = new List<AssertionRecord>();
        var prepared = rig.Prepare();
        rig.Source.AfterRead = (read, source) =>
        {
            if (read == 3)
            {
                source.MarkInternalRevisionGap();
                source.AfterRead = null;
            }
        };

        var action = rig.Coordinator.Execute(InputAction.Wheel(120));
        IntegrationFocusView view = rig.Coordinator.FocusAdapter.Last;
        Check(assertions, "arm_ok", true, prepared.Arm.Ok);
        Check(assertions, "internal_gap_rejected", true,
            view.SourceFenceBroken && view.Reason.StartsWith("SOURCE_REVISION_GAP:", StringComparison.Ordinal));
        Check(assertions, "gap_reason", "SOURCE_REVISION_GAP:0->2", view.Reason);
        Check(assertions, "raw_zero", 0L, action.RawSendCallDelta);
        Check(assertions, "c_frozen", true, action.ActiveFreezeReasons.Contains(FreezeReason.FOCUS_LOST));
        return rig.Finish(Result("I12_internal_raw_revision_gap_fail_closed", "An internal raw revision gap is rejected even when the batch endpoints are monotonic.", assertions,
            $"reason={view.Reason};raw={action.RawSendCallDelta}"));
    }

    private static ScenarioResult Result(
        string id,
        string description,
        IReadOnlyList<AssertionRecord> assertions,
        string detail) =>
        new(id, description, assertions.All(a => a.Passed), assertions, detail);

    private static void Check(List<AssertionRecord> assertions, string name, object? expected, object? actual)
    {
        bool passed = JsonSerializer.Serialize(expected) == JsonSerializer.Serialize(actual);
        assertions.Add(new AssertionRecord(name, passed, expected, actual));
    }
}
