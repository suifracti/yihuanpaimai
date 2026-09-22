using System.Diagnostics;
using System.Text.Json;
using System.Text.Json.Nodes;
using NteHost.Freeze;
using NteHost.Input;
using NteHost.Integration;
using NteHost.WindowMonitor;

namespace NteHost.WindowMonitor.Harness;

/// <summary>
/// Runs the real WindowMonitor -> production observation adapter -> A/B/C
/// coordinator path against a separately-owned, explicitly controlled Win32
/// window. The actuator is CountingRawInputBackend, so the run proves the
/// integration boundary without sending real input.
/// </summary>
internal static class ControlledIntegrationHarness
{
    private static readonly JsonSerializerOptions JsonOut = new() { WriteIndented = true };
    private const string ControlledClass = "NteV22ControlledWindow";

    public static int Run(string[] args)
    {
        string outputPath = Path.GetFullPath(Arg(
            args,
            "--output",
            Path.Combine("build", "goal-luna", "native-bridge", "controlled-integration", "integration-result.json")));

        try
        {
            (object evidence, bool ok) = RunCore(outputPath);
            WriteEvidence(outputPath, evidence);
            Emit(evidence);
            return ok ? 0 : 1;
        }
        catch (Exception ex)
        {
            var evidence = new
            {
                schemaVersion = "v2.2.integration.i1.controlled-window.v1",
                ok = false,
                productionReachable = false,
                realInputExecuted = false,
                exception = ex.GetType().Name,
                exceptionMessage = ex.Message,
            };
            WriteEvidence(outputPath, evidence);
            Emit(evidence);
            return 1;
        }
    }

    private static (object Evidence, bool Ok) RunCore(string outputPath)
    {
        using Process serve = StartServeProcess();
        JsonObject ready = ReadJsonLine(serve, "serve-ready");
        if (!string.Equals(ready["phase"]?.GetValue<string>(), "ready", StringComparison.Ordinal))
        {
            throw new InvalidOperationException($"controlled-window-not-ready:{ready.ToJsonString()}");
        }

        string imageName = ready["imageName"]?.GetValue<string>()
            ?? throw new InvalidOperationException("controlled-window-ready-missing-image");
        string className = ready["className"]?.GetValue<string>() ?? ControlledClass;
        int childPid = ready["pid"]?.GetValue<int>() ?? 0;

        var monitor = new WindowMonitor(new WindowMonitorOptions
        {
            Spec = new TargetWindowSpec(imageName, className),
            RequireVisible = true,
            SkipOwnProcessInHook = true,
            EventQueueCapacity = 4096,
            RecoveryScanMinIntervalMs = 50,
        });
        monitor.Start();

        var source = new WindowMonitorObservationSource(monitor);
        try
        {
            IntegrationWindowObservation initial = WaitForStableObservation(
                source,
                monitor,
                requireForeground: true,
                timeoutMs: 5000);

            var first = NewCoordinator(source);
            try
            {
                bool sessionStarted = first.StartSession();
                IntegrationArmResult firstArm = first.ArmCurrent();
                IntegrationActionResult firstAction = first.Execute(InputAction.Wheel(120));
                long firstRawCalls = first.Raw.SendCallCount;

                bool happyOk = sessionStarted
                    && firstArm.Ok
                    && firstAction.Ok
                    && firstAction.RawSendCallDelta == 1
                    && firstAction.RawAcceptedDelta > 0
                    && firstRawCalls == 1;

                JsonObject focusCommand = SendCommand(serve, "fg 1");
                WaitForMonitorIdle(monitor, 3000);
                IntegrationActionResult focusAction = first.Execute(InputAction.Wheel(120));
                long focusRawCalls = first.Raw.SendCallCount;
                bool focusOk = !focusAction.Ok
                    && focusAction.RawSendCallDelta == 0
                    && focusRawCalls == firstRawCalls
                    && focusAction.FocusEpoch > firstAction.FocusEpoch
                    && focusAction.ActiveFreezeReasons.Contains(FreezeReason.FOCUS_LOST);

                var focusEvidence = new
                {
                    command = focusCommand,
                    action = focusAction,
                    rawCallsBefore = firstRawCalls,
                    rawCallsAfter = focusRawCalls,
                    accepted = focusOk,
                    adapter = first.FocusAdapter.Last,
                    freezeReasons = first.Freeze.ActiveReasons,
                };

                first.Dispose();

                JsonObject returnCommand = SendCommand(serve, "fg 0");
                WaitForMonitorIdle(monitor, 3000);
                WaitForStableObservation(source, monitor, requireForeground: true, timeoutMs: 5000);

                var second = NewCoordinator(source);
                try
                {
                    bool secondSessionStarted = second.StartSession();
                    IntegrationArmResult secondArm = second.ArmCurrent();
                    IntegrationActionResult secondAction = second.Execute(InputAction.Wheel(120));
                    long secondRawCalls = second.Raw.SendCallCount;

                    JsonObject recreateCommand = SendCommand(serve, "recreate 0");
                    JsonObject recreateFocusCommand = SendCommand(serve, "fg 0");
                    WaitForMonitorIdle(monitor, 3000);
                    IntegrationActionResult recreateAction = second.Execute(InputAction.Wheel(120));
                    long recreateRawCalls = second.Raw.SendCallCount;
                    bool recreateOk = recreateCommand["hwnd"] is not null
                        && recreateFocusCommand["tookEffect"]?.GetValue<bool>() == true
                        && secondSessionStarted
                        && secondArm.Ok
                        && secondAction.Ok
                        && secondRawCalls == 1
                        && !recreateAction.Ok
                        && recreateAction.RawSendCallDelta == 0
                        && recreateRawCalls == secondRawCalls
                        && recreateAction.ActiveFreezeReasons.Contains(FreezeReason.FOCUS_LOST);

                    var identityEvidence = new
                    {
                        recreate = recreateCommand,
                        focus = recreateFocusCommand,
                        warmupAction = secondAction,
                        rejectedAction = recreateAction,
                        rawCallsBefore = secondRawCalls,
                        rawCallsAfter = recreateRawCalls,
                        accepted = recreateOk,
                        adapter = second.FocusAdapter.Last,
                        freezeReasons = second.Freeze.ActiveReasons,
                    };

                    bool ok = happyOk && focusOk && recreateOk;
                    var evidence = new
                    {
                        schemaVersion = "v2.2.integration.i1.controlled-window.v1",
                        ok,
                        productionReachable = false,
                        realInputExecuted = false,
                        controlledWindow = new
                        {
                            childPid,
                            imageName,
                            className,
                            initial = initial,
                            initialForeground = ready["grabForeground"],
                        },
                        sourceAdapter = nameof(WindowMonitorObservationSource),
                        coordinator = nameof(IntegrationCoordinator),
                        cases = new
                        {
                            happy = new
                            {
                                sessionStarted,
                                arm = firstArm,
                                action = firstAction,
                                rawCalls = firstRawCalls,
                                accepted = happyOk,
                            },
                            focusLoss = focusEvidence,
                            identityRecreate = identityEvidence,
                        },
                        final = new
                        {
                            monitorHookInstalled = monitor.IsHookInstalled,
                            monitorProcessedEvents = monitor.ProcessedEventCount,
                            monitorDroppedEvents = monitor.DroppedEventCount,
                        },
                        note = "Controlled-window integration only; the raw backend counts calls and never invokes SendInput.",
                    };

                    return (evidence, ok);
                }
                finally
                {
                    second.Dispose();
                }
            }
            finally
            {
                // Dispose is idempotent; this also covers the assertion path.
                first.Dispose();
            }
        }
        finally
        {
            source.Dispose();
            StopServeProcess(serve);
        }
    }

    private static IntegrationCoordinator NewCoordinator(IWindowObservationSource source)
    {
        return new IntegrationCoordinator(
            source,
            new FakeInputObserver(),
            new FakeCursorBackend(10, 10),
            new CountingRawInputBackend(),
            new InMemoryInputTraceSink());
    }

    private static Process StartServeProcess()
    {
        string assemblyPath = typeof(Program).Assembly.Location;
        var start = new ProcessStartInfo
        {
            UseShellExecute = false,
            RedirectStandardInput = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            CreateNoWindow = true,
            WorkingDirectory = Directory.GetCurrentDirectory(),
        };

        if (string.Equals(Path.GetExtension(assemblyPath), ".dll", StringComparison.OrdinalIgnoreCase))
        {
            start.FileName = Environment.ProcessPath
                ?? throw new InvalidOperationException("missing-dotnet-process-path");
            start.ArgumentList.Add(assemblyPath);
        }
        else
        {
            start.FileName = assemblyPath;
        }

        start.ArgumentList.Add("--mode");
        start.ArgumentList.Add("serve");
        start.ArgumentList.Add("--class");
        start.ArgumentList.Add(ControlledClass);
        start.ArgumentList.Add("--count");
        start.ArgumentList.Add("2");
        start.ArgumentList.Add("--grab-foreground");
        start.ArgumentList.Add("--width");
        start.ArgumentList.Add("420");
        start.ArgumentList.Add("--height");
        start.ArgumentList.Add("260");

        var process = new Process { StartInfo = start };
        process.ErrorDataReceived += (_, _) => { };
        if (!process.Start())
        {
            process.Dispose();
            throw new InvalidOperationException("controlled-window-process-start-failed");
        }

        process.BeginErrorReadLine();
        return process;
    }

    private static JsonObject SendCommand(Process process, string command)
    {
        process.StandardInput.WriteLine(command);
        process.StandardInput.Flush();
        return ReadJsonLine(process, $"command:{command}");
    }

    private static JsonObject ReadJsonLine(Process process, string label)
    {
        Task<string?> read = process.StandardOutput.ReadLineAsync();
        if (!read.Wait(5000))
        {
            throw new TimeoutException($"{label}-timeout");
        }

        string line = read.Result ?? throw new EndOfStreamException($"{label}-eof");
        try
        {
            return JsonNode.Parse(line)?.AsObject()
                ?? throw new InvalidDataException($"{label}-not-object");
        }
        catch (JsonException ex)
        {
            throw new InvalidDataException($"{label}-invalid-json:{line}", ex);
        }
    }

    private static IntegrationWindowObservation WaitForStableObservation(
        WindowMonitorObservationSource source,
        WindowMonitor monitor,
        bool requireForeground,
        int timeoutMs)
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

            Thread.Sleep(50);
        }

        throw new TimeoutException(
            $"stable-observation-timeout;last={last?.ToString()};busy={monitor.IsWorkerBusyForDiagnostics};queue={monitor.RawQueueCount}");
    }

    private static void WaitForMonitorIdle(WindowMonitor monitor, int timeoutMs)
    {
        long deadline = Environment.TickCount64 + timeoutMs;
        while (Environment.TickCount64 < deadline)
        {
            if (!monitor.IsWorkerBusyForDiagnostics
                && monitor.RawQueueCount == 0
                && monitor.RawIngestionInFlightForDiagnostics == 0)
            {
                return;
            }

            Thread.Sleep(25);
        }

        throw new TimeoutException($"monitor-idle-timeout;busy={monitor.IsWorkerBusyForDiagnostics};queue={monitor.RawQueueCount}");
    }

    private static void StopServeProcess(Process process)
    {
        try
        {
            if (!process.HasExited)
            {
                process.StandardInput.WriteLine("exit");
                process.StandardInput.Flush();
                process.WaitForExit(1500);
            }
        }
        catch
        {
            // The finally path below still makes a best-effort child cleanup.
        }

        try
        {
            if (!process.HasExited)
            {
                process.Kill(entireProcessTree: true);
                process.WaitForExit(1500);
            }
        }
        catch
        {
            // The child is a harness-owned process; there is nothing else to release.
        }
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
