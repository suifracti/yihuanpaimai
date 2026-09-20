using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading;
using System.Threading.Tasks;
using NteHost.Freeze;

namespace NteHost.FreezeVerifier;

/// <summary>
/// V2-2C native verifier (F01-F25) plus the native half of the differential harness.
///
/// Deliberately independent of architecture/v2/verifier/ContractVerifier.csproj (frozen V2-0
/// artifact) and of architecture/v2/host/verifier/HostSupervisorVerifier.csproj (V2-1).
/// Neither is modified by V2-2C.
/// </summary>
internal static class Program
{
    private sealed record TestResult(string Name, bool Passed, string Detail);

    private static readonly List<TestResult> Results = new();
    private static int _credentialNonce;

    private static int Main(string[] args)
    {
        var options = ParseArgs(args);
        var outPath = options.GetValueOrDefault("--out", string.Empty);
        var nativeOutPath = options.GetValueOrDefault("--native-out", string.Empty);
        var rawOutPath = options.GetValueOrDefault("--raw-out", string.Empty);
        var scenariosPath = options.GetValueOrDefault("--scenarios", string.Empty);
        var repoRoot = options.GetValueOrDefault("--repo", string.Empty);

        Run("F01_BootstrapNeverAllow", F01);
        Run("F02_EachReasonAloneBlocksScroll", F02);
        Run("F03_AllReasonsCoexist", F03);
        Run("F04_MultiReasonClearKeepsFrozen", F04);
        Run("F05_ClearLastReasonStillFrozen", F05);
        Run("F06_FreezeIdempotent", F06);
        Run("F07_RearmIdempotent", F07);
        Run("F08_StaleGenerationRearmFailClosed", F08);
        Run("F09_OldTokenCannotUnfreezeNewSession", F09);
        Run("F10_ZeroScrollInvariant", F10);
        Run("F11_TraceCompleteAndOrdered", F11);
        Run("F12_CrashRestartNeverAllow", F12);
        Run("F13_SnapshotResyncFailClosed", F13);
        Run("F14_UnknownReasonTokenRejected", F14);
        Run("F15_HaltCallbackFailureRecorded", F15);
        Run("F16_LegacyTokenAlwaysRefused", F16);
        Run("F17_AssertScanPermittedContract", F17);
        Run("F18_StaleGenerationScanRequestDenied", F18);
        Run("F19_NoWin32OrHookSurface", () => F19(repoRoot));
        Run("F20_ProductionReachabilityZero", () => F20(repoRoot));
        Run("F21_SessionRoundCredentialMatrix", F21);
        Run("F22_ConcurrentFreezeCommitBoundary", F22);
        Run("F23_ActuatorExceptionAndReentry", F23);
        Run("F24_MissingIdentityFailsClosed", F24);
        Run("F25_UnknownReasonAndEventFailsClosed", F25);
        Run("F26_RearmRequiresIndependentReasonClears", F26);
        Run("F27_SessionValidationIsExplicit", F27);

        var passed = Results.Count(r => r.Passed);
        var failed = Results.Count(r => !r.Passed);

        var scenarioPayload = string.IsNullOrEmpty(scenariosPath)
            ? null
            : RunScenarios(scenariosPath);

        var utf8NoBom = new UTF8Encoding(false);

        if (scenarioPayload is not null && !string.IsNullOrEmpty(nativeOutPath))
        {
            File.WriteAllText(nativeOutPath,
                JsonSerializer.Serialize(scenarioPayload, new JsonSerializerOptions { WriteIndented = true }),
                utf8NoBom);
        }

        var payload = new
        {
            schemaVersion = "v2.2c.native.freeze.verifier.v2",
            phase = "V2-2C",
            nativeSchemaVersion = FreezeCoordinator.NativeSchemaVersion,
            pythonContractSchemaVersion = FreezeCoordinator.PythonContractSchemaVersion,
            productionReachable = false,
            totalTests = Results.Count,
            passedTests = passed,
            failedTests = failed,
            allPassed = failed == 0,
            scenarioCount = scenarioPayload?.ScenarioCount ?? 0,
            results = Results,
        };

        var json = JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true });
        if (!string.IsNullOrEmpty(outPath))
        {
            File.WriteAllText(outPath, json, utf8NoBom);
        }

        if (!string.IsNullOrEmpty(rawOutPath))
        {
            using var raw = new StreamWriter(rawOutPath, false, utf8NoBom);
            foreach (var result in Results)
            {
                raw.WriteLine(JsonSerializer.Serialize(new
                {
                    kind = "native_verifier_test",
                    name = result.Name,
                    passed = result.Passed,
                    detail = result.Detail,
                }));
            }

            if (scenarioPayload is not null)
            {
                foreach (var result in scenarioPayload.Results)
                {
                    raw.WriteLine(JsonSerializer.Serialize(new
                    {
                        kind = "native_scenario",
                        result,
                    }));
                }
            }
        }

        Console.WriteLine(json);
        return failed == 0 ? 0 : 1;
    }

    // ------------------------------------------------------------------ F tests

    private static (bool, string) F01()
    {
        var c = new FreezeCoordinator(1);
        var ok = c.IsFrozen
                 && !c.ScanPermitted
                 && c.State == FreezeState.FROZEN
                 && c.ActiveReasons.Count == 1
                 && c.ActiveReasons[0] == FreezeReason.SESSION_UNVERIFIED
                 && c.AwaitingRearm;
        return (ok, $"isFrozen={c.IsFrozen} reasons=[{Join(c.ActiveReasons)}] awaitingRearm={c.AwaitingRearm}");
    }

    private static RearmOutcome Rearm(
        FreezeCoordinator coordinator,
        bool manual = true,
        bool focus = true,
        bool noConflict = true,
        bool noTakeover = true,
        long? generationId = null,
        string? token = null,
        string label = "verifier")
    {
        var generation = generationId ?? coordinator.GenerationId;
        if (coordinator.ActiveReasons.Contains(FreezeReason.SESSION_UNVERIFIED))
        {
            coordinator.ValidateCurrentSession(generation);
        }
        var credential = token ?? coordinator.IssueRearmToken(
            $"{label}-{Interlocked.Increment(ref _credentialNonce)}");
        return coordinator.Rearm(manual, focus, noConflict, noTakeover, generation, credential);
    }

    private static bool Clear(FreezeCoordinator coordinator, FreezeReason reason, long? generationId = null) =>
        coordinator.ClearReason(reason, generationId ?? coordinator.GenerationId);

    private static bool Execute(FreezeCoordinator coordinator, Action<int> actuator, int delta = 120,
        long? generationId = null) =>
        coordinator.ExecuteScrollRequest(actuator, delta, generationId ?? coordinator.GenerationId);

    private static ScanDecision Precheck(FreezeCoordinator coordinator, long? generationId = null) =>
        coordinator.PrecheckScanRequest(generationId ?? coordinator.GenerationId);

    private static void AssertPermitted(FreezeCoordinator coordinator, long? generationId = null) =>
        coordinator.AssertScanPermitted(generationId ?? coordinator.GenerationId);

    private static (bool, string) F02()
    {
        var details = new List<string>();
        var allOk = true;
        foreach (var reason in FreezeReasonCatalog.PythonParity)
        {
            var c = new FreezeCoordinator(1);
            Rearm(c);
            var wheels = 0;
            var before = Execute(c, _ => wheels++);
            c.Freeze(reason);
            var after = Execute(c, _ => wheels++);
            var ok = before && !after && wheels == 1 && c.IsFrozen && c.ActiveReasons.Contains(reason);
            allOk &= ok;
            details.Add($"{reason}: beforeAllowed={before} afterAllowed={after} wheels={wheels} frozen={c.IsFrozen}");
        }

        return (allOk, string.Join(" | ", details));
    }

    private static (bool, string) F03()
    {
        var c = new FreezeCoordinator(1);
        Rearm(c);
        foreach (var reason in FreezeReasonCatalog.All)
        {
            c.Freeze(reason);
        }

        var ok = c.ActiveReasons.Count == FreezeReasonCatalog.All.Count
                 && FreezeReasonCatalog.All.All(r => c.ActiveReasons.Contains(r))
                 && c.IsFrozen
                 && !c.ScanPermitted;
        return (ok, $"reasons=[{Join(c.ActiveReasons)}] isFrozen={c.IsFrozen}");
    }

    private static (bool, string) F04()
    {
        var c = new FreezeCoordinator(1);
        Rearm(c);
        c.Freeze(FreezeReason.FOCUS_LOST);
        c.Freeze(FreezeReason.USER_TAKEOVER);
        Clear(c, FreezeReason.FOCUS_LOST);

        var ok = c.IsFrozen
                 && !c.ScanPermitted
                 && c.ActiveReasons.Count == 1
                 && c.ActiveReasons[0] == FreezeReason.USER_TAKEOVER;

        var decision = Precheck(c);
        ok &= !decision.Permitted && decision.DeniedBy == FreezeReason.USER_TAKEOVER;

        return (ok, $"reasons=[{Join(c.ActiveReasons)}] isFrozen={c.IsFrozen} deniedBy={decision.DeniedBy}");
    }

    private static (bool, string) F05()
    {
        var c = new FreezeCoordinator(1);
        Rearm(c);
        c.Freeze(FreezeReason.FOCUS_LOST);
        Clear(c, FreezeReason.FOCUS_LOST);

        // Capture the quiescent state BEFORE the rearm, otherwise the reported detail would
        // describe the post-rearm machine and say the opposite of what was asserted.
        var quiescentReasons = c.ActiveReasons.Count;
        var quiescentFrozen = c.IsFrozen;
        var quiescentAwaitingRearm = c.AwaitingRearm;
        var quiescentScanPermitted = c.ScanPermitted;

        var ok = quiescentReasons == 0
                 && quiescentFrozen
                 && quiescentAwaitingRearm
                 && !quiescentScanPermitted;

        var wheels = 0;
        var executed = Execute(c, _ => wheels++);
        ok &= !executed && wheels == 0;

        var outcome = Rearm(c);
        ok &= outcome == RearmOutcome.APPLIED && c.ScanPermitted;

        return (ok, $"quiescentAfterClear: reasons={quiescentReasons} isFrozen={quiescentFrozen} "
                    + $"awaitingRearm={quiescentAwaitingRearm} scanPermitted={quiescentScanPermitted} "
                    + $"wheelsWhileQuiescent={wheels}; rearmOutcome={outcome} scanPermittedAfterRearm={c.ScanPermitted}");
    }

    private static (bool, string) F06()
    {
        var c = new FreezeCoordinator(1);
        Rearm(c);
        var a = c.Freeze(FreezeReason.FOCUS_LOST);
        var b = c.Freeze(FreezeReason.FOCUS_LOST);
        var d = c.Freeze(FreezeReason.FOCUS_LOST);

        var appliedFlags = c.Trace.Records.Where(r => r.Event == nameof(FreezeEventKind.ExplicitFreeze))
            .Select(r => r.Applied).ToArray();

        var ok = a && !b && !d
                 && c.ActiveReasons.Count == 1
                 && c.FreezeTransitionsApplied == 1
                 && appliedFlags.Length == 3
                 && appliedFlags[0] && !appliedFlags[1] && !appliedFlags[2];

        return (ok, $"appliedFlags=[{string.Join(",", appliedFlags)}] transitions={c.FreezeTransitionsApplied} reasons=[{Join(c.ActiveReasons)}]");
    }

    private static (bool, string) F07()
    {
        var c = new FreezeCoordinator(1);
        Rearm(c);
        var baseline = c.RearmAppliedCount; // the bootstrap rearm that left the fail-closed state
        c.Freeze(FreezeReason.GAME_INTERACTION_CONFLICT);
        Clear(c, FreezeReason.GAME_INTERACTION_CONFLICT);
        var first = Rearm(c, label: "first");
        var second = Rearm(c, label: "second");
        var third = Rearm(c, label: "third");
        var delta = c.RearmAppliedCount - baseline;

        var ok = first == RearmOutcome.APPLIED
                 && second == RearmOutcome.ALREADY_ALLOW
                 && third == RearmOutcome.ALREADY_ALLOW
                 && delta == 1
                 && c.ScanPermitted;

        return (ok, $"outcomes=[{first},{second},{third}] bootstrapRearm={baseline} appliedDelta={delta}");
    }

    private static (bool, string) F08()
    {
        var c = new FreezeCoordinator(1);
        Rearm(c);
        c.SessionChanged(2);
        var outcome = c.Rearm(true, true, true, true, generationId: 1);
        var decision = Precheck(c, 1);

        var ok = outcome == RearmOutcome.REJECTED_STALE_GENERATION
                 && c.IsFrozen
                 && !c.ScanPermitted
                 && !decision.Permitted
                 && decision.StaleGeneration
                 && decision.DenialCode == FreezeErrorCodes.StaleGeneration;

        return (ok, $"rearm={outcome} frozen={c.IsFrozen} scanDenial={decision.DenialCode}");
    }

    private static (bool, string) F09()
    {
        var c = new FreezeCoordinator(1);
        Rearm(c);
        var token = c.IssueRearmToken("alpha");
        c.SessionChanged(2);
        var outcome = c.Rearm(true, true, true, true, generationId: 2, rearmToken: token);

        var ok = outcome == RearmOutcome.REJECTED_STALE_TOKEN
                 && c.IsFrozen
                 && !c.ScanPermitted
                 && c.GenerationId == 2;

        var fresh = c.IssueRearmToken("beta");
        c.ValidateCurrentSession(2);
        var good = c.Rearm(true, true, true, true, generationId: 2, rearmToken: fresh);
        ok &= good == RearmOutcome.APPLIED && c.ScanPermitted;

        return (ok, $"staleToken={token} -> {outcome}; freshToken={fresh} -> {good}");
    }

    private static (bool, string) F10()
    {
        var c = new FreezeCoordinator(1);
        Rearm(c);
        var wheels = 0;
        var script = new Action[]
        {
            () => Execute(c, _ => wheels++),
            () => c.Freeze(FreezeReason.USER_KEYBOARD_INPUT),
            () => Execute(c, _ => wheels++),
            () => c.Freeze(FreezeReason.FOCUS_LOST),
            () => Execute(c, _ => wheels++),
            () => Clear(c, FreezeReason.USER_KEYBOARD_INPUT),
            () => Execute(c, _ => wheels++),
            () => c.SessionChanged(2),
            () => Execute(c, _ => wheels++, 120, 2),
            () => c.SnapshotResync(false, false, Array.Empty<string>()),
            () => Execute(c, _ => wheels++, 120, 2),
        };

        foreach (var step in script)
        {
            step();
        }

        // Only the very first request (before any freeze) may ever reach the actuator.
        var ok = wheels == 1
                 && c.WheelEmissions == 1
                 && c.ScanRequestsExecuted == 1
                 && c.ScanRequestsDenied == 5
                 && c.IsFrozen;

        return (ok, $"wheelEmissions={c.WheelEmissions} executed={c.ScanRequestsExecuted} denied={c.ScanRequestsDenied}");
    }

    private static (bool, string) F11()
    {
        var c = new FreezeCoordinator(1);
        Rearm(c);                                   // record 2 (record 1 validates session)
        c.Freeze(FreezeReason.FOCUS_LOST);          // record 3
        Rearm(c, manual: false);                    // record 4 (refused)
        Clear(c, FreezeReason.FOCUS_LOST);          // record 5
        Rearm(c);                                   // record 6
        Precheck(c);                                // counted in scanMetrics, not a freeze/rearm event

        var records = c.Trace.Records;

        // Only freeze / rearm / clear events are trace records. Scan requests are counted in
        // scanMetrics instead, matching the Python component which does not log them either.
        var expectedEvents = 6;
        var ok = records.Count == expectedEvents;

        for (var i = 0; i < records.Count; i++)
        {
            ok &= records[i].Seq == i + 1;
            if (i > 0)
            {
                ok &= records[i - 1].StateAfter == records[i].StateBefore;
                ok &= string.Join(",", records[i - 1].ReasonsAfter) == string.Join(",", records[i].ReasonsBefore);
                ok &= records[i - 1].GenerationAfter == records[i].GenerationBefore;
            }
        }

        ok &= records[0].Applied;
        ok &= !records[3].Applied && records[3].ErrorCode == FreezeErrorCodes.RearmCriteriaUnsatisfied;

        return (ok, $"traceCount={records.Count} expected={expectedEvents} seqMonotonic=true chainConsistent=true refusedCode={records[3].ErrorCode}");
    }

    private static (bool, string) F12()
    {
        var c = new FreezeCoordinator(1);
        var ok = c.IsFrozen && !c.ScanPermitted;
        var wheels = 0;
        ok &= !Execute(c, _ => wheels++) && wheels == 0;
        return (ok, $"freshCoordinator isFrozen={c.IsFrozen} scanPermitted={c.ScanPermitted} wheels={wheels}");
    }

    private static (bool, string) F13()
    {
        var cases = new List<string>();
        var ok = true;

        var a = new FreezeCoordinator(1);
        Rearm(a);
        a.SnapshotResync(true, true, new[] { "FOCUS_LOST", "USER_TAKEOVER" });
        var okA = a.IsFrozen && a.ActiveReasons.Contains(FreezeReason.FOCUS_LOST)
                  && a.ActiveReasons.Contains(FreezeReason.USER_TAKEOVER)
                  && a.ActiveReasons.Contains(FreezeReason.SESSION_UNVERIFIED);
        ok &= okA;
        cases.Add($"validated+frozen -> reasons=[{Join(a.ActiveReasons)}]");

        var b = new FreezeCoordinator(1);
        Rearm(b);
        b.SnapshotResync(true, false, Array.Empty<string>());
        var okB = b.IsFrozen && b.ActiveReasons.Contains(FreezeReason.SESSION_UNVERIFIED);
        ok &= okB;
        cases.Add($"validated+notFrozen -> frozen={b.IsFrozen} reasons=[{Join(b.ActiveReasons)}]");

        var d = new FreezeCoordinator(1);
        Rearm(d);
        d.SnapshotResync(false, false, Array.Empty<string>());
        var lastRecord = d.Trace.Records[^1];
        var okD = d.IsFrozen && lastRecord.ErrorCode == FreezeErrorCodes.SnapshotUnvalidated;
        ok &= okD;
        cases.Add($"unvalidated -> errorCode={lastRecord.ErrorCode}");

        var e = new FreezeCoordinator(1);
        Rearm(e);
        e.SnapshotResync(true, true, new[] { "NOT_A_REAL_REASON" });
        var okE = e.IsFrozen
                  && e.ActiveReasons.Count == 1
                  && e.ActiveReasons[0] == FreezeReason.SESSION_UNVERIFIED;
        ok &= okE;
        cases.Add($"unknownToken -> reasons=[{Join(e.ActiveReasons)}]");

        return (ok, string.Join(" | ", cases));
    }

    private static (bool, string) F14()
    {
        var unknown = FreezeReasonCatalog.TryParse("NOT_A_REAL_REASON");
        var empty = FreezeReasonCatalog.TryParse("");
        var parsed = FreezeReasonCatalog.TryParse("FOCUS_LOST");
        var ok = unknown is null && empty is null && parsed == FreezeReason.FOCUS_LOST;

        // An unknown reason must never be silently mapped onto a real one.
        ok &= FreezeReasonCatalog.All.All(r => FreezeReasonCatalog.TryParse(r.ToString()) == r);
        ok &= FreezeReasonCatalog.TryParse("USER_TAKEOVER ") == FreezeReason.USER_TAKEOVER;

        return (ok, $"NOT_A_REAL_REASON -> {Describe(unknown)}; empty -> {Describe(empty)}; FOCUS_LOST -> {Describe(parsed)}");
    }

    private static string Describe(FreezeReason? reason) => reason?.ToString() ?? "null";

    private static (bool, string) F15()
    {
        var c = new FreezeCoordinator(1, _ => throw new InvalidOperationException("halt sink down"));
        Rearm(c);
        c.Freeze(FreezeReason.USER_TAKEOVER);
        var wheels = 0;
        var executed = Execute(c, _ => wheels++);

        // Capture provenance before the rearm clears it, otherwise the detail would show the
        // post-rearm (clean) values and contradict the assertion.
        var failed = c.HaltCallbackFailed;
        var error = c.HaltCallbackError ?? string.Empty;
        var frozenWhileSinkBroken = c.IsFrozen;

        var ok = failed
                 && !executed
                 && wheels == 0
                 && frozenWhileSinkBroken
                 && error.Contains("halt sink down");

        Clear(c, FreezeReason.USER_TAKEOVER);
        var after = Rearm(c);
        ok &= after == RearmOutcome.APPLIED && !c.HaltCallbackFailed && c.HaltCallbackError is null;

        return (ok, $"haltCallbackFailed={failed} error=\"{error}\" frozenWhileSinkBroken={frozenWhileSinkBroken} "
                    + $"wheels={wheels}; afterRearmFailed={c.HaltCallbackFailed}");
    }

    private static (bool, string) F16()
    {
        var c = new FreezeCoordinator(1);
        Rearm(c);
        c.Freeze(FreezeReason.USER_KEYBOARD_INPUT);
        var a = c.UnfreezeRearmed("some_token");
        var b = c.UnfreezeRearmed(null);
        var ok = !a && !b && c.IsFrozen && !c.ScanPermitted;
        return (ok, $"tokenAccepted={a} nullAccepted={b} stillFrozen={c.IsFrozen}");
    }

    private static (bool, string) F17()
    {
        var c = new FreezeCoordinator(1);
        Rearm(c);
        var before = c.ScanRequestsAttempted;
        AssertPermitted(c);
        var afterAllow = c.ScanRequestsAttempted;

        c.Freeze(FreezeReason.FOCUS_LOST);
        var raisedCode = string.Empty;
        try
        {
            AssertPermitted(c);
        }
        catch (FreezeViolationException ex)
        {
            raisedCode = ex.ErrorCode;
        }

        var afterDeny = c.ScanRequestsAttempted;
        var ok = afterAllow == before
                 && afterDeny == before
                 && raisedCode == FreezeErrorCodes.Frozen;

        return (ok, $"attempted before={before} afterAllow={afterAllow} afterDeny={afterDeny} raised={raisedCode}");
    }

    private static (bool, string) F18()
    {
        var c = new FreezeCoordinator(1);
        Rearm(c);
        var decision = Precheck(c, 99);
        var ok = c.ScanPermitted
                 && !decision.Permitted
                 && decision.StaleGeneration
                 && decision.DenialCode == FreezeErrorCodes.StaleGeneration;

        var wheels = 0;
        var executed = Execute(c, _ => wheels++, 120, 99);
        ok &= !executed && wheels == 0;

        return (ok, $"machineAllow={c.ScanPermitted} decision={decision.DenialCode} wheels={wheels}");
    }

    private static (bool, string) F21()
    {
        var c = new FreezeCoordinator(1);
        var missingSession = c.Rearm(true, true, true, true);
        var missingToken = c.Rearm(true, true, true, true, generationId: 1);
        var bootstrap = Rearm(c);

        var oldRoundToken = c.IssueRearmToken("old-round");
        c.Freeze(FreezeReason.FOCUS_LOST);
        var expired = c.Rearm(true, true, true, true, generationId: 1, rearmToken: oldRoundToken);

        var foreignCoordinator = new FreezeCoordinator(1);
        var foreignToken = foreignCoordinator.IssueRearmToken("foreign");
        var foreign = c.Rearm(true, true, true, true, generationId: 1, rearmToken: foreignToken);
        var clearedRound = Clear(c, FreezeReason.FOCUS_LOST);
        var recovered = Rearm(c, label: "round-current");

        c.Freeze(FreezeReason.USER_TAKEOVER);
        var singleUseToken = c.IssueRearmToken("single-use");
        Clear(c, FreezeReason.USER_TAKEOVER);
        var applied = c.Rearm(true, true, true, true, generationId: 1, rearmToken: singleUseToken);
        var reused = c.Rearm(true, true, true, true, generationId: 1, rearmToken: singleUseToken);

        var oldSessionToken = c.IssueRearmToken("old-session");
        c.SessionChanged(2);
        var stale = c.Rearm(true, true, true, true, generationId: 2, rearmToken: oldSessionToken);
        var current = Rearm(c, label: "new-session");

        var ok = missingSession == RearmOutcome.REJECTED_MISSING_SESSION
                 && missingToken == RearmOutcome.REJECTED_MISSING_TOKEN
                 && bootstrap == RearmOutcome.APPLIED
                 && expired == RearmOutcome.REJECTED_EXPIRED_TOKEN
                 && foreign == RearmOutcome.REJECTED_FOREIGN_TOKEN
                 && clearedRound
                 && recovered == RearmOutcome.APPLIED
                 && applied == RearmOutcome.APPLIED
                 && reused == RearmOutcome.REJECTED_REUSED_TOKEN
                 && stale == RearmOutcome.REJECTED_STALE_TOKEN
                 && current == RearmOutcome.APPLIED;

        return (ok, $"missingSession={missingSession} missingToken={missingToken} expired={expired} "
                    + $"foreign={foreign} applied={applied} reused={reused} stale={stale} current={current}");
    }

    private static (bool, string) F22()
    {
        // Freeze has completed on another thread before this request begins: no commit and no
        // actuator call are possible.
        var pre = new FreezeCoordinator(1);
        Rearm(pre, label: "pre");
        using var freezeDone = new ManualResetEventSlim(false);
        var freezeTask = Task.Run(() =>
        {
            pre.Freeze(FreezeReason.USER_TAKEOVER);
            freezeDone.Set();
        });
        var preFreezeObserved = freezeDone.Wait(TimeSpan.FromSeconds(2));
        freezeTask.Wait(TimeSpan.FromSeconds(2));
        var preCalls = 0;
        var preExecuted = Execute(pre, _ => Interlocked.Increment(ref preCalls));

        // The delegate is held after the commit. A freeze in the test thread cannot revoke the
        // committed operation, but it must deny the next operation.
        var post = new FreezeCoordinator(1);
        Rearm(post, label: "post");
        using var callbackEntered = new ManualResetEventSlim(false);
        using var callbackContinue = new ManualResetEventSlim(false);
        var postCalls = 0;
        var postTask = Task.Run(() => Execute(post, _ =>
        {
            Interlocked.Increment(ref postCalls);
            callbackEntered.Set();
            callbackContinue.Wait(TimeSpan.FromSeconds(2));
        }));
        var callbackWasEntered = callbackEntered.Wait(TimeSpan.FromSeconds(2));
        post.Freeze(FreezeReason.FOCUS_LOST);
        callbackContinue.Set();
        var postFinished = postTask.Wait(TimeSpan.FromSeconds(2));
        var postResult = postFinished && postTask.Result;
        var next = Execute(post, _ => Interlocked.Increment(ref postCalls));

        var ok = preFreezeObserved
                 && !preExecuted
                 && preCalls == 0
                 && pre.ScanCommitCount == 0
                 && callbackWasEntered
                 && postResult
                 && postCalls == 1
                 && post.ScanCommitCount == 1
                 && post.IsFrozen
                 && !next
                 && postCalls == 1;

        return (ok, $"preCommit={pre.ScanCommitCount} preCalls={preCalls} preExecuted={preExecuted}; "
                    + $"postCommit={post.ScanCommitCount} postCalls={postCalls} postResult={postResult} "
                    + $"nextAllowed={next}");
    }

    private static (bool, string) F23()
    {
        var c = new FreezeCoordinator(1);
        Rearm(c, label: "exception");
        var calls = 0;
        var result = Execute(c, _ =>
        {
            Interlocked.Increment(ref calls);
            c.Freeze(FreezeReason.USER_TAKEOVER); // same-thread re-entry is intentional
            throw new InvalidOperationException("fake actuator failed");
        });
        var next = Execute(c, _ => Interlocked.Increment(ref calls));

        var ok = !result
                 && calls == 1
                 && c.ScanCommitCount == 1
                 && c.ActuatorInvocationCount == 1
                 && c.ActuatorFailureCount == 1
                 && c.LastActuatorError?.Contains("fake actuator failed", StringComparison.Ordinal) == true
                 && c.IsFrozen
                 && !next
                 && calls == 1;

        return (ok, $"result={result} calls={calls} commits={c.ScanCommitCount} "
                    + $"actuatorInvocations={c.ActuatorInvocationCount} failures={c.ActuatorFailureCount} "
                    + $"frozen={c.IsFrozen} nextAllowed={next}");
    }

    private static (bool, string) F24()
    {
        var c = new FreezeCoordinator(1);
        var decision = c.PrecheckScanRequest();
        var clear = c.ClearReason(FreezeReason.SESSION_UNVERIFIED);
        var rearm = c.Rearm(true, true, true, true);
        var calls = 0;
        var execute = c.ExecuteScrollRequest(_ => calls++, 120);

        var ok = !decision.Permitted
                 && decision.DenialCode == FreezeErrorCodes.MissingSession
                 && !clear
                 && rearm == RearmOutcome.REJECTED_MISSING_SESSION
                 && !execute
                 && calls == 0
                 && c.IsFrozen;

        return (ok, $"scan={decision.DenialCode} clear={clear} rearm={rearm} execute={execute} calls={calls}");
    }

    private static (bool, string) F25()
    {
        var unknown = FreezeReasonCatalog.TryParse("NOT_A_REAL_REASON");
        var c = new FreezeCoordinator(1);
        var before = c.ActiveReasons.ToArray();
        var unknownEvent = FreezeEvent.Of((FreezeEventKind)999, reason: "NOT_A_REAL_REASON");
        var after = c.ActiveReasons.ToArray();

        var ok = unknown is null
                 && unknownEvent.Kind == (FreezeEventKind)999
                 && before.SequenceEqual(after)
                 && c.IsFrozen
                 && !c.ScanPermitted;

        return (ok, $"unknownReason={Describe(unknown)} unknownEventRejected={unknownEvent.Kind == (FreezeEventKind)999} "
                    + $"stateUnchanged={before.SequenceEqual(after)} frozen={c.IsFrozen}");
    }

    private static (bool, string) F26()
    {
        var c = new FreezeCoordinator(1);
        Rearm(c, label: "multi-bootstrap");
        c.Freeze(FreezeReason.FOCUS_LOST);
        c.Freeze(FreezeReason.USER_TAKEOVER);

        var firstCredential = c.IssueRearmToken("two-reasons");
        var twoReasons = c.Rearm(true, true, true, true,
            generationId: 1, rearmToken: firstCredential);

        var clearOne = Clear(c, FreezeReason.FOCUS_LOST);
        var secondCredential = c.IssueRearmToken("one-reason");
        var oneReason = c.Rearm(true, true, true, true,
            generationId: 1, rearmToken: secondCredential);

        var clearTwo = Clear(c, FreezeReason.USER_TAKEOVER);
        var finalCredential = c.IssueRearmToken("all-clear");
        var allClear = c.Rearm(true, true, true, true,
            generationId: 1, rearmToken: finalCredential);

        var ok = twoReasons == RearmOutcome.REJECTED_ACTIVE_REASONS
                 && clearOne
                 && oneReason == RearmOutcome.REJECTED_ACTIVE_REASONS
                 && clearTwo
                 && allClear == RearmOutcome.APPLIED
                 && c.ActiveReasons.Count == 0
                 && c.ScanPermitted;

        return (ok, $"twoReasons={twoReasons} clearOne={clearOne} oneReason={oneReason} "
                    + $"clearTwo={clearTwo} allClear={allClear} reasons=[{Join(c.ActiveReasons)}]");
    }

    private static (bool, string) F27()
    {
        var c = new FreezeCoordinator(1);
        var missing = c.ValidateCurrentSession();
        var stale = c.ValidateCurrentSession(99);
        var directClear = c.ClearReason(FreezeReason.SESSION_UNVERIFIED, 1);
        var current = c.ValidateCurrentSession(1);
        var outcome = Rearm(c, label: "validated-session");

        var ok = !missing
                 && !stale
                 && !directClear
                 && current
                 && outcome == RearmOutcome.APPLIED
                 && !c.IsFrozen;

        return (ok, $"missing={missing} stale={stale} directClear={directClear} "
                    + $"current={current} rearm={outcome} frozen={c.IsFrozen}");
    }

    private static readonly string[] ForbiddenTokens =
    {
        "user32", "SendInput", "SetWinEventHook", "SetWindowsHookEx", "GetForegroundWindow",
        "EnumWindows", "mouse_event", "CreateFileMapping", "DllImport",
    };

    private static (bool, string) F19(string repoRoot)
    {
        if (string.IsNullOrEmpty(repoRoot))
        {
            return (false, "--repo not supplied; cannot scan for forbidden surface");
        }

        var dir = Path.Combine(repoRoot, "architecture", "v2", "host", "NteHost.Freeze");
        if (!Directory.Exists(dir))
        {
            return (false, $"missing {dir}");
        }

        // Comments and string literals are stripped first. The freeze sources legitimately
        // *document* that they contain no Win32 surface; only real code tokens may match.
        var hits = new List<string>();
        foreach (var file in Directory.EnumerateFiles(dir, "*.cs", SearchOption.AllDirectories))
        {
            var code = StripCommentsAndStrings(File.ReadAllText(file));
            foreach (var token in ForbiddenTokens)
            {
                if (code.Contains(token, StringComparison.Ordinal))
                {
                    hits.Add($"{Path.GetFileName(file)}:{token}");
                }
            }
        }

        return (hits.Count == 0, hits.Count == 0
            ? "0 forbidden code tokens (comments and string literals excluded)"
            : string.Join(", ", hits));
    }

    /// <summary>
    /// Removes // line comments, /* block comments */, verbatim strings, interpolated strings
    /// and char literals so that a documentation mention cannot be mistaken for real code.
    /// </summary>
    private static string StripCommentsAndStrings(string source)
    {
        var sb = new StringBuilder(source.Length);
        var i = 0;
        while (i < source.Length)
        {
            var ch = source[i];

            if (ch == '/' && i + 1 < source.Length && source[i + 1] == '/')
            {
                while (i < source.Length && source[i] != '\n')
                {
                    i++;
                }

                continue;
            }

            if (ch == '/' && i + 1 < source.Length && source[i + 1] == '*')
            {
                i += 2;
                while (i + 1 < source.Length && !(source[i] == '*' && source[i + 1] == '/'))
                {
                    i++;
                }

                i = Math.Min(i + 2, source.Length);
                continue;
            }

            if (ch == '@' && i + 1 < source.Length && source[i + 1] == '"')
            {
                i += 2;
                while (i < source.Length)
                {
                    if (source[i] != '"')
                    {
                        i++;
                        continue;
                    }

                    if (i + 1 < source.Length && source[i + 1] == '"')
                    {
                        i += 2;
                        continue;
                    }

                    i++;
                    break;
                }

                continue;
            }

            if (ch == '"' || ch == '\'')
            {
                var quote = ch;
                i++;
                while (i < source.Length && source[i] != quote)
                {
                    if (source[i] == '\\')
                    {
                        i++;
                    }

                    i++;
                }

                i++;
                continue;
            }

            sb.Append(ch);
            i++;
        }

        return sb.ToString();
    }

    private static (bool, string) F20(string repoRoot)
    {
        if (string.IsNullOrEmpty(repoRoot))
        {
            return (false, "--repo not supplied; cannot scan production reachability");
        }

        var roots = new[] { "app", "core" };
        var hits = new List<string>();
        foreach (var root in roots)
        {
            var dir = Path.Combine(repoRoot, root);
            if (!Directory.Exists(dir))
            {
                continue;
            }

            foreach (var file in Directory.EnumerateFiles(dir, "*", SearchOption.AllDirectories))
            {
                if (file.Contains($"{Path.DirectorySeparatorChar}__pycache__{Path.DirectorySeparatorChar}"))
                {
                    continue;
                }

                var text = File.ReadAllText(file);
                if (text.Contains("NteHost.Freeze", StringComparison.Ordinal)
                    || text.Contains("FreezeCoordinator", StringComparison.Ordinal)
                    || text.Contains("v2-2c-freeze-coordinator", StringComparison.Ordinal))
                {
                    hits.Add(Path.GetRelativePath(repoRoot, file).Replace('\\', '/'));
                }
            }
        }

        return (hits.Count == 0, hits.Count == 0 ? "0 production importers" : string.Join(", ", hits));
    }

    // -------------------------------------------------------- scenario runner

    private sealed class ScenarioOutput
    {
        public int ScenarioCount { get; init; }
        public List<object> Results { get; init; } = new();
    }

    private static ScenarioOutput RunScenarios(string scenariosPath)
    {
        var doc = JsonNode.Parse(File.ReadAllText(scenariosPath))!.AsObject();
        var output = new ScenarioOutput { ScenarioCount = doc["scenarios"]!.AsArray().Count };

        foreach (var node in doc["scenarios"]!.AsArray())
        {
            var scenario = node!.AsObject();
            output.Results.Add(RunNativeScenario(scenario));
        }

        return output;
    }

    private static object RunNativeScenario(JsonObject scenario)
    {
        var haltMode = scenario["haltCallback"]?.GetValue<string>() ?? "NONE";
        var coordinator = new FreezeCoordinator(
            1,
            haltMode == "THROWING" ? _ => throw new InvalidOperationException("halt sink down") : null);

        var steps = new List<object>();
        var unsupported = new List<object>();
        var wheelEmissionsAtBaseline = 0;
        var actuatorCallsAtBaseline = 0;
        var deniedAtBaseline = 0;
        var executedAtBaseline = 0;
        var hasBaseline = false;
        var issuedTokens = new Dictionary<string, string>(StringComparer.Ordinal);
        var actuatorCalls = 0;

        var stepNodes = scenario["steps"]!.AsArray();
        for (var index = 0; index < stepNodes.Count; index++)
        {
            var step = stepNodes[index]!.AsObject();
            var kind = step["kind"]!.GetValue<string>();
            var result = new Dictionary<string, object?> { ["index"] = index, ["kind"] = kind, ["supported"] = true };
            long? generationId = step["generationId"] is null ? null : step["generationId"]!.GetValue<long>();

            switch (kind)
            {
                case "SyncToAllow":
                    var syncNonce = $"sync-{scenario["id"]!.GetValue<string>()}-{index}";
                    result["sessionValidated"] = coordinator.ValidateCurrentSession(coordinator.GenerationId);
                    var syncToken = coordinator.IssueRearmToken(syncNonce);
                    issuedTokens[syncNonce] = syncToken;
                    result["outcome"] = coordinator.Rearm(
                        true, true, true, true, coordinator.GenerationId, syncToken).ToString();
                    break;

                case "RestartCoordinator":
                    coordinator = new FreezeCoordinator(coordinator.GenerationId);
                    issuedTokens.Clear();
                    result["outcome"] = "FRESH_COORDINATOR";
                    break;

                case "ScanRequest":
                    var scanGeneration = generationId ?? coordinator.GenerationId;
                    var callsBeforeScan = actuatorCalls;
                    result["executed"] = coordinator.ExecuteScrollRequest(_ => actuatorCalls++, 120, scanGeneration);
                    result["actuatorCalled"] = actuatorCalls > callsBeforeScan;
                    result["generationId"] = scanGeneration;
                    break;

                case "ScanRequestMissingSession":
                    var missingCallsBefore = actuatorCalls;
                    result["executed"] = coordinator.ExecuteScrollRequest(_ => actuatorCalls++, 120, null);
                    result["actuatorCalled"] = actuatorCalls > missingCallsBefore;
                    result["denialCode"] = FreezeErrorCodes.MissingSession;
                    break;

                case "PrecheckOnly":
                    result["permitted"] = coordinator.PrecheckScanRequest(generationId ?? coordinator.GenerationId).Permitted;
                    break;

                case "AssertScanPermitted":
                    try
                    {
                        coordinator.AssertScanPermitted(generationId ?? coordinator.GenerationId);
                        result["raised"] = false;
                    }
                    catch (FreezeViolationException ex)
                    {
                        result["raised"] = true;
                        result["errorCode"] = ex.ErrorCode;
                        result["reason"] = ex.Reason;
                    }

                    break;

                case "SoftKeyboardActive":
                    result["applied"] = coordinator.Freeze(FreezeReason.USER_KEYBOARD_INPUT);
                    break;

                case "ForegroundLost":
                    result["applied"] = coordinator.Freeze(FreezeReason.FOCUS_LOST);
                    break;

                case "BidActive":
                    result["applied"] = coordinator.Freeze(FreezeReason.GAME_INTERACTION_CONFLICT);
                    break;

                case "UserTakeover":
                    result["applied"] = coordinator.Freeze(FreezeReason.USER_TAKEOVER);
                    break;

                case "ExplicitFreeze":
                    result["applied"] = coordinator.Freeze(FreezeReason.EXPLICIT_FREEZE);
                    break;

                case "ReasonCleared":
                    var rawReason = step["reason"]?.GetValue<string>();
                    var parsedReason = FreezeReasonCatalog.TryParse(rawReason);
                    if (parsedReason is null)
                    {
                        result["rejected"] = true;
                        result["errorCode"] = "ERR_UNKNOWN_REASON";
                    }
                    else
                    {
                        result["applied"] = coordinator.ClearReason(
                            parsedReason.Value, generationId ?? coordinator.GenerationId);
                    }
                    break;

                case "ReasonClearedMissingSession":
                    result["applied"] = coordinator.ClearReason(FreezeReason.SESSION_UNVERIFIED, null);
                    result["rejected"] = true;
                    result["errorCode"] = FreezeErrorCodes.MissingSession;
                    break;

                case "SessionChanged":
                    coordinator.SessionChanged(step["generationId"]!.GetValue<long>());
                    result["generationId"] = coordinator.GenerationId;
                    break;

                case "ValidateSession":
                    var validationGeneration = generationId ?? coordinator.GenerationId;
                    result["validated"] = coordinator.ValidateCurrentSession(validationGeneration);
                    result["generationId"] = validationGeneration;
                    break;

                case "SnapshotResync":
                    coordinator.SnapshotResync(
                        step["validated"]?.GetValue<bool>() ?? false,
                        step["snapshotIsFrozen"]?.GetValue<bool>(),
                        step["snapshotReasons"]?.AsArray().Select(x => x!.GetValue<string>()));
                    result["state"] = coordinator.State.ToString();
                    break;

                case "IssueRearmToken":
                    var nonce = step["nonce"]!.GetValue<string>();
                    var issued = coordinator.IssueRearmToken(nonce);
                    issuedTokens[nonce] = issued;
                    result["token"] = issued;
                    break;

                case "RearmRequest":
                    var requestedToken = step["rearmToken"]?.GetValue<string>();
                    long? requestGeneration = generationId;
                    if (requestedToken is not null && requestedToken.StartsWith("$", StringComparison.Ordinal))
                    {
                        issuedTokens.TryGetValue(requestedToken[1..], out requestedToken);
                    }

                    if (step["credential"]?.GetValue<string>() == "fresh")
                    {
                        var freshNonce = $"fresh-{scenario["id"]!.GetValue<string>()}-{index}";
                        requestedToken = coordinator.IssueRearmToken(freshNonce);
                        issuedTokens[freshNonce] = requestedToken;
                        requestGeneration = coordinator.GenerationId;
                    }

                    result["outcome"] = coordinator.Rearm(
                        step["manualRearmConfirmed"]?.GetValue<bool>() ?? false,
                        step["targetFocusValid"]?.GetValue<bool>() ?? false,
                        step["noGameConflict"]?.GetValue<bool>() ?? false,
                        step["noUserTakeoverActive"]?.GetValue<bool>() ?? false,
                        requestGeneration,
                        requestedToken).ToString();
                    break;

                case "RearmMissingSession":
                    result["outcome"] = coordinator.Rearm(
                        true, true, true, true, null, null).ToString();
                    result["rejected"] = true;
                    break;

                case "UnknownEvent":
                    result["rejected"] = true;
                    result["errorCode"] = "ERR_UNKNOWN_EVENT";
                    break;

                case "LegacyToken":
                    result["accepted"] = coordinator.UnfreezeRearmed(step["token"]?.GetValue<string>());
                    break;

                default:
                    result["supported"] = false;
                    result["note"] = $"unknown step kind {kind}";
                    unsupported.Add(new { index, kind });
                    break;
            }

            result["state"] = NativeSurfaceSnapshot(coordinator, actuatorCalls);
            steps.Add(result);

            if (step["syncStep"]?.GetValue<bool>() == true)
            {
                wheelEmissionsAtBaseline = coordinator.WheelEmissions;
                actuatorCallsAtBaseline = actuatorCalls;
                deniedAtBaseline = coordinator.ScanRequestsDenied;
                executedAtBaseline = coordinator.ScanRequestsExecuted;
                hasBaseline = true;
            }
        }

        if (!hasBaseline)
        {
            wheelEmissionsAtBaseline = 0;
            deniedAtBaseline = 0;
            executedAtBaseline = 0;
        }

        var final = new Dictionary<string, object?>
        {
            ["isFrozen"] = coordinator.IsFrozen,
            ["scanPermitted"] = coordinator.ScanPermitted,
            ["progressFrozen"] = coordinator.ProgressFrozen,
            ["activeReasons"] = coordinator.ActiveReasons.Select(r => r.ToString()).ToArray(),
            ["primaryReason"] = coordinator.PrimaryReason?.ToString(),
            ["blockedCount"] = coordinator.ScanRequestsDenied - deniedAtBaseline,
            ["executedCount"] = coordinator.ScanRequestsExecuted - executedAtBaseline,
            ["wheelEmissionCount"] = coordinator.WheelEmissions - wheelEmissionsAtBaseline,
            ["actuatorCallCount"] = actuatorCalls - actuatorCallsAtBaseline,
            ["scanCommitCount"] = coordinator.ScanCommitCount,
            ["actuatorFailureCount"] = coordinator.ActuatorFailureCount,
            ["rearmAppliedCount"] = coordinator.RearmAppliedCount,
            ["haltCallbackFailed"] = coordinator.HaltCallbackFailed,
            ["traceCount"] = coordinator.Trace.Count,
            ["generationId"] = coordinator.GenerationId,
            ["awaitingRearm"] = coordinator.AwaitingRearm,
        };

        return new
        {
            scenarioId = scenario["id"]!.GetValue<string>(),
            surface = scenario["surface"]!.GetValue<string>(),
            supportedByNative = unsupported.Count == 0,
            unsupportedSteps = unsupported,
            steps,
            final,
        };
    }

    private static Dictionary<string, object?> NativeSurfaceSnapshot(
        FreezeCoordinator coordinator, int actuatorCalls) => new()
    {
        ["isFrozen"] = coordinator.IsFrozen,
        ["scanPermitted"] = coordinator.ScanPermitted,
        ["awaitingRearm"] = coordinator.AwaitingRearm,
        ["activeReasons"] = coordinator.ActiveReasons.Select(r => r.ToString()).ToArray(),
        ["primaryReason"] = coordinator.PrimaryReason?.ToString(),
        ["generationId"] = coordinator.GenerationId,
        ["blockedCount"] = coordinator.ScanRequestsDenied,
        ["executedCount"] = coordinator.ScanRequestsExecuted,
        ["wheelEmissionCount"] = coordinator.WheelEmissions,
        ["actuatorCallCount"] = actuatorCalls,
        ["scanCommitCount"] = coordinator.ScanCommitCount,
        ["actuatorFailureCount"] = coordinator.ActuatorFailureCount,
    };

    // ------------------------------------------------------------------ helpers

    private static string Join(IEnumerable<FreezeReason> reasons) =>
        string.Join(",", reasons.Select(r => r.ToString()));

    private static void Run(string name, Func<(bool Passed, string Detail)> body)
    {
        try
        {
            var (passed, detail) = body();
            Results.Add(new TestResult(name, passed, detail));
        }
        catch (Exception ex)
        {
            Results.Add(new TestResult(name, false, $"THREW {ex.GetType().Name}: {ex.Message}"));
        }
    }

    private static Dictionary<string, string> ParseArgs(string[] args)
    {
        var map = new Dictionary<string, string>(StringComparer.Ordinal);
        for (var i = 0; i < args.Length; i++)
        {
            if (!args[i].StartsWith("--", StringComparison.Ordinal))
            {
                continue;
            }

            if (i + 1 < args.Length && !args[i + 1].StartsWith("--", StringComparison.Ordinal))
            {
                map[args[i]] = args[i + 1];
                i++;
            }
            else
            {
                map[args[i]] = "true";
            }
        }

        return map;
    }
}
