using System.Text.Json;
using NteHost.Freeze;
using NteHost.Input;
using NteHost.Integration;
using NteHost.WindowMonitor;

namespace NteHost.WindowMonitor.Harness;

/// <summary>
/// Minimal real-window Integration probe. It observes the real target spec but
/// keeps the actuator fake: the only raw backend is CountingRawInputBackend.
/// The probe waits for the user to produce one real focus loss and return, then
/// checks that the old armed path remains denied without any raw call.
/// </summary>
internal static class LiveIntegrationHarness
{
    private static readonly JsonSerializerOptions JsonOut = new() { WriteIndented = true };

    public static int Run(string[] args)
    {
        string outputPath = Path.GetFullPath(Arg(
            args,
            "--output",
            Path.Combine("build", "goal-luna", "native-bridge", "real-window", "integration-live.json")));

        try
        {
            (object evidence, bool ok) = RunCore(args);
            WriteEvidence(outputPath, evidence);
            Emit(evidence);
            return ok ? 0 : 1;
        }
        catch (Exception ex)
        {
            var evidence = new
            {
                schemaVersion = "v2.2.integration.i1.real-window.v1",
                ok = false,
                productionReachable = false,
                realInputPathReachable = false,
                realInputExecuted = false,
                exception = ex.GetType().Name,
                exceptionMessage = ex.Message,
            };
            WriteEvidence(outputPath, evidence);
            Emit(evidence);
            return 1;
        }
    }

    private static (object Evidence, bool Ok) RunCore(string[] args)
    {
        string specImage = Arg(args, "--spec-image", "htgame.exe");
        string specClass = Arg(args, "--spec-class", "UnrealWindow");
        int targetWaitMs = int.Parse(Arg(args, "--target-wait-ms", "10000"));
        int focusWaitMs = int.Parse(Arg(args, "--focus-wait-ms", "45000"));
        int pollMs = int.Parse(Arg(args, "--poll-ms", "50"));

        var monitor = new WindowMonitor(new WindowMonitorOptions
        {
            Spec = new TargetWindowSpec(specImage, specClass),
            RequireVisible = true,
            SkipOwnProcessInHook = true,
            EventQueueCapacity = 4096,
        });
        monitor.Start();
        var source = new WindowMonitorObservationSource(monitor);

        try
        {
            IntegrationWindowObservation targetObservation = WaitForStableObservation(
                source, monitor, requireForeground: false, targetWaitMs, pollMs);
            Emit(new
            {
                phase = "real-target-found",
                spec = new { processImageName = specImage, windowClass = specClass },
                hookInstalled = monitor.IsHookInstalled,
                observation = targetObservation,
            });

            IntegrationWindowObservation foregroundObservation = WaitForStableObservation(
                source, monitor, requireForeground: true, focusWaitMs, pollMs);

            var observer = new FakeInputObserver { Name = "real-window-fake-input-observer" };
            var cursor = new FakeCursorBackend(10, 10);
            var raw = new CountingRawInputBackend();
            var trace = new InMemoryInputTraceSink();
            using var coordinator = new IntegrationCoordinator(source, observer, cursor, raw, trace);

            bool sessionStarted = coordinator.StartSession();
            IntegrationArmResult arm = coordinator.ArmCurrent();
            IntegrationActionResult normalAction = coordinator.Execute(InputAction.Wheel(120));
            long normalRawCalls = raw.SendCallCount;
            IntegrationFocusView armedView = coordinator.FocusAdapter.Last;

            Emit(new
            {
                phase = "real-foreground-armed",
                observation = foregroundObservation,
                sessionStarted,
                arm,
                action = normalAction,
                rawCalls = normalRawCalls,
                focus = armedView,
            });

            if (!sessionStarted || !arm.Ok || !normalAction.Ok)
            {
                return (Evidence(
                    specImage,
                    specClass,
                    monitor,
                    targetObservation,
                    foregroundObservation,
                    productionReachable: true,
                    realInputPathReachable: false,
                    realInputExecuted: false,
                    blocker: "foreground-arm-or-dry-run-action-failed",
                    normalAction,
                    null,
                    null,
                    normalRawCalls,
                    normalRawCalls,
                    normalRawCalls,
                    coordinator), false);
            }

            Emit(new
            {
                phase = "await-user-focus-loss",
                instruction = "保持真实输入关闭；请手动切到其他窗口一次，再切回游戏窗口。",
            });

            IntegrationFocusView? lostView = WaitForView(
                coordinator,
                view => view.FocusChanged
                    && view.ForegroundId == 0
                    && view.FocusEpoch > armedView.FocusEpoch,
                focusWaitMs,
                pollMs);
            if (lostView is null)
            {
                return (Evidence(
                    specImage,
                    specClass,
                    monitor,
                    targetObservation,
                    foregroundObservation,
                    productionReachable: true,
                    realInputPathReachable: false,
                    realInputExecuted: false,
                    blocker: "focus-loss-not-observed-within-window",
                    normalAction,
                    null,
                    null,
                    normalRawCalls,
                    raw.SendCallCount,
                    raw.SendCallCount,
                    coordinator), false);
            }

            IntegrationActionResult lostAction = coordinator.Execute(InputAction.Wheel(120));
            long lostRawCalls = raw.SendCallCount;
            Emit(new
            {
                phase = "real-focus-lost",
                focus = lostView,
                action = lostAction,
                rawCalls = lostRawCalls,
                rawDelta = lostRawCalls - normalRawCalls,
                freezeReasons = coordinator.Freeze.ActiveReasons.Select(reason => reason.ToString()).ToArray(),
            });

            IntegrationFocusView? regainedView = WaitForView(
                coordinator,
                view => view.FocusChanged
                    && view.ForegroundId == armedView.TargetId
                    && view.FocusEpoch > lostView.FocusEpoch,
                focusWaitMs,
                pollMs);
            if (regainedView is null)
            {
                return (Evidence(
                    specImage,
                    specClass,
                    monitor,
                    targetObservation,
                    foregroundObservation,
                    productionReachable: true,
                    realInputPathReachable: false,
                    realInputExecuted: false,
                    blocker: "focus-regain-not-observed-within-window",
                    normalAction,
                    lostAction,
                    null,
                    normalRawCalls,
                    lostRawCalls,
                    raw.SendCallCount,
                    coordinator), false);
            }

            IntegrationActionResult regainedAction = coordinator.Execute(InputAction.Wheel(120));
            long regainedRawCalls = raw.SendCallCount;

            bool lostClosed = !lostAction.Ok && lostRawCalls - normalRawCalls == 0;
            bool regainDidNotReuse = !regainedAction.Ok
                && regainedRawCalls - lostRawCalls == 0
                && regainedAction.ActiveFreezeReasons.Contains(FreezeReason.FOCUS_LOST);
            bool ok = lostClosed && regainDidNotReuse;

            var evidence = Evidence(
                specImage,
                specClass,
                monitor,
                targetObservation,
                foregroundObservation,
                productionReachable: true,
                realInputPathReachable: false,
                realInputExecuted: false,
                blocker: ok ? "NONE" : "focus-gate-or-raw-delta-failed",
                normalAction,
                lostAction,
                regainedAction,
                normalRawCalls,
                lostRawCalls,
                regainedRawCalls,
                coordinator,
                lostView,
                regainedView,
                lostClosed,
                regainDidNotReuse);
            return (evidence, ok);
        }
        finally
        {
            source.Dispose();
        }
    }

    private static object Evidence(
        string specImage,
        string specClass,
        WindowMonitor monitor,
        IntegrationWindowObservation targetObservation,
        IntegrationWindowObservation foregroundObservation,
        bool productionReachable,
        bool realInputPathReachable,
        bool realInputExecuted,
        string blocker,
        IntegrationActionResult normalAction,
        IntegrationActionResult? lostAction,
        IntegrationActionResult? regainedAction,
        long normalRawCalls,
        long lostRawCalls,
        long regainedRawCalls,
        IntegrationCoordinator coordinator,
        IntegrationFocusView? lostView = null,
        IntegrationFocusView? regainedView = null,
        bool? lostClosed = null,
        bool? regainDidNotReuse = null)
    {
        return new
        {
            schemaVersion = "v2.2.integration.i1.real-window.v1",
            ok = blocker == "NONE",
            productionReachable,
            realInputPathReachable,
            realInputExecuted,
            spec = new { processImageName = specImage, windowClass = specClass },
            target = new
            {
                targetHwnd = targetObservation.Snapshot.TargetHwnd,
                targetPid = targetObservation.Snapshot.TargetPid,
                targetIdentity = targetObservation.Snapshot.TargetIdentity,
                generation = targetObservation.Snapshot.Generation,
            },
            foregroundObservation,
            normal = new
            {
                action = normalAction,
                rawCalls = normalRawCalls,
            },
            focusLoss = new
            {
                view = lostView,
                action = lostAction,
                rawCalls = lostRawCalls,
                rawDelta = lostAction is null ? (long?)null : lostRawCalls - normalRawCalls,
                closed = lostClosed,
            },
            focusRegain = new
            {
                view = regainedView,
                action = regainedAction,
                rawCalls = regainedRawCalls,
                rawDelta = regainedAction is null ? (long?)null : regainedRawCalls - lostRawCalls,
                oldArmNotReused = regainDidNotReuse,
            },
            finalFreezeReasons = coordinator.Freeze.ActiveReasons.Select(reason => reason.ToString()).ToArray(),
            monitor = new
            {
                hookInstalled = monitor.IsHookInstalled,
                processedEvents = monitor.ProcessedEventCount,
                droppedEvents = monitor.DroppedEventCount,
                rawCallbacks = monitor.RawCallbackCount,
            },
            blocker,
            note = "Real target observation only; CountingRawInputBackend never invokes SendInput.",
        };
    }

    private static IntegrationWindowObservation WaitForStableObservation(
        WindowMonitorObservationSource source,
        WindowMonitor monitor,
        bool requireForeground,
        int timeoutMs,
        int pollMs)
    {
        long deadline = Environment.TickCount64 + timeoutMs;
        IntegrationWindowObservation? last = null;
        while (Environment.TickCount64 < deadline)
        {
            last = source.Read();
            bool identityPresent = last.Snapshot.TargetIdentity is { IsPresent: true };
            bool foreground = !requireForeground || last.Snapshot.IsTargetForeground;
            if (!last.Overflowed
                && !last.HasPendingEvents
                && !last.HasGap
                && last.Snapshot.IsTargetAlive
                && identityPresent
                && foreground)
            {
                return last;
            }

            Thread.Sleep(pollMs);
        }

        throw new TimeoutException(
            $"stable-observation-timeout;requireForeground={requireForeground};last={last};busy={monitor.IsWorkerBusyForDiagnostics};queue={monitor.RawQueueCount}");
    }

    private static IntegrationFocusView? WaitForView(
        IntegrationCoordinator coordinator,
        Func<IntegrationFocusView, bool> predicate,
        int timeoutMs,
        int pollMs)
    {
        long deadline = Environment.TickCount64 + timeoutMs;
        while (Environment.TickCount64 < deadline)
        {
            IntegrationFocusView view = coordinator.FocusAdapter.CaptureView();
            if (predicate(view))
            {
                return view;
            }

            Thread.Sleep(pollMs);
        }

        return null;
    }

    private static string Arg(string[] args, string name, string fallback)
    {
        for (var i = 0; i < args.Length - 1; i++)
        {
            if (args[i] == name)
            {
                return args[i + 1];
            }
        }

        return fallback;
    }

    private static void WriteEvidence(string path, object evidence)
    {
        string? directory = Path.GetDirectoryName(path);
        if (!string.IsNullOrEmpty(directory))
        {
            Directory.CreateDirectory(directory);
        }

        File.WriteAllText(path, JsonSerializer.Serialize(evidence, JsonOut));
    }

    private static void Emit(object payload) =>
        Console.WriteLine(JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = false }));
}
