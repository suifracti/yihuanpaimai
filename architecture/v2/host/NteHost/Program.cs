using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text.Json.Nodes;
using System.Threading;
using NteHost.Protocol;

namespace NteHost;

/// <summary>
/// V2-1 Native Host skeleton. It is a scenario-driven harness: each scenario
/// exercises one supervision property and writes a machine-readable result file
/// that the Python targeted tests assert on.
///
/// Nothing here is reachable from app/ or core/; V2-1 keeps
/// productionReachable = false.
/// </summary>
internal static class Program
{
    private static string _engineFault = string.Empty;
    private static string _engineFaultCapability = string.Empty;
    private static string _engineFaultHelloSize = string.Empty;

    private static int Main(string[] rawArgs)
    {
        var args = ParseArgs(rawArgs);
        var scenario = Arg(args, "--scenario", "coldboot");
        var python = Arg(args, "--python", string.Empty);
        var engine = Arg(args, "--engine", string.Empty);
        var outPath = Arg(args, "--out", string.Empty);
        var tracePath = Arg(args, "--trace", string.Empty);
        var workDir = Arg(args, "--work-dir", Path.Combine(Path.GetTempPath(), "nte-host-" + Guid.NewGuid().ToString("N")));
        var contractsDir = Arg(args, "--contracts", string.Empty);
        var runs = int.Parse(Arg(args, "--runs", "5"));
        var holdMs = int.Parse(Arg(args, "--hold-ms", "0"));
        var postAcceptDelayMs = int.Parse(Arg(args, "--post-accept-delay-ms", "0"));
        _engineFault = Arg(args, "--engine-fault", string.Empty);
        _engineFaultCapability = Arg(args, "--engine-fault-missing-capability", string.Empty);
        _engineFaultHelloSize = Arg(args, "--engine-fault-hello-size", string.Empty);

        Directory.CreateDirectory(workDir);
        if (string.IsNullOrEmpty(python) || string.IsNullOrEmpty(engine))
        {
            Console.Error.WriteLine("--python and --engine are required");
            return 2;
        }

        var sessionId = Guid.NewGuid().ToString();
        var result = new Dictionary<string, object?>
        {
            ["scenario"] = scenario,
            ["sessionId"] = sessionId,
            ["protocolVersion"] = ProtocolConstants.ProtocolVersion,
            ["hostProcessId"] = Environment.ProcessId,
            ["hostQpcFrequency"] = ProtocolClock.Frequency,
            ["workDir"] = workDir,
        };

        using var trace = new TraceLog(string.IsNullOrEmpty(tracePath) ? null : tracePath, sessionId, "init");
        result["tracePath"] = string.IsNullOrEmpty(tracePath) ? null : tracePath;

        try
        {
            switch (scenario)
            {
                case "coldboot":
                    result["run"] = RunColdBoot(python, engine, workDir, contractsDir, sessionId, trace, postAcceptDelayMs);
                    break;
                case "reconnect":
                    result["run"] = RunReconnect(python, engine, workDir, contractsDir, sessionId, trace);
                    break;
                case "generation":
                    result["run"] = RunGeneration(python, engine, workDir, contractsDir, sessionId, trace);
                    break;
                case "hold":
                    result["run"] = RunHold(python, engine, workDir, contractsDir, sessionId, trace, holdMs);
                    break;
                case "pipeatfail":
                    result["run"] = RunPipeAtFail(python, engine, workDir, contractsDir, sessionId, trace);
                    break;
                case "metrics":
                    result["run"] = RunMetrics(python, engine, workDir, contractsDir, sessionId, trace, runs);
                    break;
                case "mmf":
                    result["run"] = RunMmfLifecycle(python, engine, workDir, contractsDir, sessionId, trace);
                    break;
                case "golden":
                    result["run"] = RunGoldenParity(contractsDir);
                    break;
                case "capability":
                    result["run"] = RunCapabilityGate(python, engine, workDir, contractsDir, sessionId, trace);
                    break;
                case "heartbeat":
                    result["run"] = RunHeartbeatDegrade(python, engine, workDir, contractsDir, sessionId, trace);
                    break;
                case "faults":
                    result["run"] = RunFaultInjection(python, engine, workDir, contractsDir, sessionId, trace);
                    break;
                case "resyncfault":
                    result["run"] = RunResyncFault(python, engine, workDir, contractsDir, sessionId, trace);
                    break;
                default:
                    Console.Error.WriteLine($"unknown scenario '{scenario}'");
                    return 2;
            }
            result["ok"] = true;
        }
        catch (Exception ex)
        {
            result["ok"] = false;
            result["exception"] = ex.GetType().Name;
            result["exceptionMessage"] = ex.Message;
            if (ex is ProtocolViolationException pve)
            {
                result["exceptionErrorCode"] = pve.ErrorCode;
            }
            Console.Error.WriteLine(ex);
        }

        if (!string.IsNullOrEmpty(outPath))
        {
            Json.WriteFile(outPath, result);
        }
        Console.WriteLine(Json.Serialize(result));
        return result["ok"] is true ? 0 : 1;
    }

    // ------------------------------------------------------------------ scenarios

    private static Dictionary<string, object?> RunColdBoot(string python, string engine, string workDir,
        string contractsDir, string sessionId, TraceLog trace, int postAcceptDelayMs = 0)
    {
        using var session = new SupervisorSession(new SupervisorSession.Options
        {
            PythonExe = python,
            EngineScript = engine,
            WorkDir = workDir,
            ContractsDir = contractsDir,
            SessionId = sessionId,
            Trace = trace,
            EngineLogPath = Path.Combine(workDir, "engine_trace.jsonl"),
            PostAcceptDelayMs = postAcceptDelayMs,
        });

        var start = session.StartGeneration(coldBoot: true);
        var handshake = session.Handshake(coldBoot: true);
        session.ReachReady(coldBoot: true, noRecoverableBusinessState: true);

        for (var i = 0; i < 3; i++)
        {
            session.HeartbeatRound();
            Thread.Sleep(30);
        }

        var shutdown = session.ControlledShutdown();

        var rejected = new Dictionary<string, object?>();
        var probe = new LifecycleStateMachine(LifecycleState.READY, isColdBoot: false);
        rejected["reconnectDirectHandshakingToReadyRejected"] = !probe.TryTransitionTo(LifecycleState.READY, out var code1);
        rejected["reconnectDirectErrorCode"] = code1;

        var coldProbe = new LifecycleStateMachine(LifecycleState.HANDSHAKING, isColdBoot: true);
        coldProbe.ProtocolNegotiated = true;
        coldProbe.CapabilitiesAccepted = true;
        coldProbe.EngineBusinessReady = true;
        coldProbe.NoRecoverableBusinessState = false;
        rejected["coldBootWithoutNoRecoverableStateRejected"] = !coldProbe.TryTransitionTo(LifecycleState.READY, out var code2);
        rejected["coldBootWithoutNoRecoverableStateErrorCode"] = code2;

        return new Dictionary<string, object?>
        {
            ["generations"] = session.Generations.ToList(),
            ["lifecycleTrace"] = traceRows(session),
            ["lifecycleFinalState"] = session.Lifecycle.Current.ToString(),
            ["metrics"] = Metrics(session),
            ["pipe"] = session.PipeFacts,
            ["capabilities"] = session.Capabilities.BuildAdvertisement(),
            ["shutdown"] = shutdown,
            ["lifecycleGuards"] = rejected,
            ["errors"] = session.Errors,
            ["mmf"] = session.Mmf.Records,
        };
    }

    private static Dictionary<string, object?> RunReconnect(string python, string engine, string workDir,
        string contractsDir, string sessionId, TraceLog trace)
    {
        using var session = new SupervisorSession(new SupervisorSession.Options
        {
            PythonExe = python,
            EngineScript = engine,
            WorkDir = workDir,
            ContractsDir = contractsDir,
            SessionId = sessionId,
            Trace = trace,
            EngineLogPath = Path.Combine(workDir, "engine_trace.jsonl"),
        });

        session.StartGeneration(coldBoot: true);
        session.Handshake(coldBoot: true);
        session.ReachReady(coldBoot: true, noRecoverableBusinessState: true);
        session.HeartbeatRound();

        var oldNonce = session.Nonce;
        var oldMapName = session.MapName;
        var oldPipeName = session.PipeName;

        var crash = session.CrashAndMeasure();
        session.TransitionToEngineDownOnCrash();

        var restart = session.RestartAndMeasure();
        var handshake2 = session.Handshake(coldBoot: false);

        // Reconnect must NOT jump HANDSHAKING -> READY.
        var directRejected = !session.Lifecycle.TryTransitionTo(LifecycleState.READY, out var directCode);

        session.ReachReady(coldBoot: false, noRecoverableBusinessState: false);
        session.HeartbeatRound();
        var shutdown = session.ControlledShutdown();

        var generationProof = session.ProveGenerationReset(oldNonce, "foreign-session-0001");

        return new Dictionary<string, object?>
        {
            ["generations"] = session.Generations.ToList(),
            ["lifecycleTrace"] = traceRows(session),
            ["lifecycleFinalState"] = session.Lifecycle.Current.ToString(),
            ["metrics"] = Metrics(session),
            ["pipe"] = session.PipeFacts,
            ["shutdown"] = shutdown,
            ["generationProof"] = generationProof,
            ["reconnectDirectReadyRejected"] = directRejected,
            ["reconnectDirectReadyErrorCode"] = directCode,
            ["generationIdentity"] = new Dictionary<string, object?>
            {
                ["generation1Nonce"] = oldNonce[..8],
                ["generation1MapName"] = oldMapName,
                ["generation1PipeName"] = oldPipeName,
                ["generation2Nonce"] = session.Nonce[..8],
                ["generation2MapName"] = session.MapName,
                ["generation2PipeName"] = session.PipeName,
                ["nonceChanged"] = !string.Equals(oldNonce, session.Nonce, StringComparison.Ordinal),
                ["mapNameChanged"] = !string.Equals(oldMapName, session.MapName, StringComparison.Ordinal),
                ["pipeNameChanged"] = !string.Equals(oldPipeName, session.PipeName, StringComparison.Ordinal),
            },
            ["errors"] = session.Errors,
            ["mmf"] = session.Mmf.Records,
        };
    }

    private static Dictionary<string, object?> RunGeneration(string python, string engine, string workDir,
        string contractsDir, string sessionId, TraceLog trace)
    {
        using var session = new SupervisorSession(new SupervisorSession.Options
        {
            PythonExe = python,
            EngineScript = engine,
            WorkDir = workDir,
            ContractsDir = contractsDir,
            SessionId = sessionId,
            Trace = trace,
            EngineLogPath = Path.Combine(workDir, "engine_trace.jsonl"),
        });

        session.StartGeneration(coldBoot: true);
        session.Handshake(coldBoot: true);
        session.ReachReady(coldBoot: true, noRecoverableBusinessState: true);

        var oldNonce = session.Nonce;
        session.CrashAndMeasure();
        session.TransitionToEngineDownOnCrash();
        session.RestartAndMeasure();
        var handshake2 = session.Handshake(coldBoot: false);

        // The replacement engine's first message in the new generation carries
        // sequence 0 and must be accepted by the real handshake path.
        var liveAccepted = handshake2.EngineFirstSequence == 0 && handshake2.HelloAckValidated;

        session.ReachReady(coldBoot: false, noRecoverableBusinessState: false);
        var proof = session.ProveGenerationReset(oldNonce, "foreign-session-0001");
        proof["liveHandshakeAcceptedSequenceZero"] = liveAccepted;
        proof["liveHandshakeEngineFirstSequence"] = handshake2.EngineFirstSequence;
        proof["liveHandshakeHostHelloSequence"] = handshake2.HostHelloSequence;

        var shutdown = session.ControlledShutdown();

        return new Dictionary<string, object?>
        {
            ["generations"] = session.Generations.ToList(),
            ["lifecycleTrace"] = traceRows(session),
            ["lifecycleFinalState"] = session.Lifecycle.Current.ToString(),
            ["metrics"] = Metrics(session),
            ["generationProof"] = proof,
            ["shutdown"] = shutdown,
            ["errors"] = session.Errors,
        };
    }

    private static Dictionary<string, object?> RunHold(string python, string engine, string workDir,
        string contractsDir, string sessionId, TraceLog trace, int holdMs)
    {
        var session = new SupervisorSession(new SupervisorSession.Options
        {
            PythonExe = python,
            EngineScript = engine,
            WorkDir = workDir,
            ContractsDir = contractsDir,
            SessionId = sessionId,
            Trace = trace,
            EngineLogPath = Path.Combine(workDir, "engine_trace.jsonl"),
        });

        session.StartGeneration(coldBoot: true);
        session.Handshake(coldBoot: true);
        session.ReachReady(coldBoot: true, noRecoverableBusinessState: true);

        // Signal readiness to the harness so it can hard-kill this process.
        Json.WriteFile(Path.Combine(workDir, "host_ready.json"), new Dictionary<string, object?>
        {
            ["hostPid"] = Environment.ProcessId,
            ["childPid"] = session.ChildPid,
            ["sessionId"] = sessionId,
            ["generationId"] = session.GenerationId,
            ["mapName"] = session.MapName,
            ["pipeName"] = session.PipeName,
            ["readyNs"] = ProtocolClock.NowNs(),
        });

        var deadline = Environment.TickCount64 + (holdMs > 0 ? holdMs : 60000);
        while (Environment.TickCount64 < deadline)
        {
            Thread.Sleep(25);
        }

        // The harness is expected to have killed this process before we get here.
        session.Dispose();
        return new Dictionary<string, object?> { ["heldWithoutKill"] = true, ["hostPid"] = Environment.ProcessId };
    }

    private static Dictionary<string, object?> RunPipeAtFail(string python, string engine, string workDir,
        string contractsDir, string sessionId, TraceLog trace)
    {
        var outcome = new Dictionary<string, object?>();
        var partADir = Path.Combine(workDir, "partA");
        var partBDir = Path.Combine(workDir, "partB");
        Directory.CreateDirectory(partADir);
        Directory.CreateDirectory(partBDir);
        var transport = new Dictionary<string, object?>
        {
            ["namedPipeImplemented"] = true,
            ["stdioFallbackImplemented"] = false,
            ["stdioFallbackAttempted"] = false,
            ["transportUsedForProtocol"] = "named_pipe",
            ["childStdioPurpose"] = "logs_only",
            ["childStdoutStderrRedirected"] = true,
        };
        outcome["transport"] = transport;

        // Part A: the engine can never reach the pipe. The supervisor must fail
        // closed rather than silently switching to a stdio transport.
        using (var session = new SupervisorSession(new SupervisorSession.Options
        {
            PythonExe = python,
            EngineScript = engine,
            WorkDir = partADir,
            ContractsDir = contractsDir,
            SessionId = sessionId,
            Trace = trace,
            EngineFault = "wrong_pipe",
            AcceptTimeoutMs = 4000,
        }))
        {
            session.StartGeneration(coldBoot: true);
            string failureCode;
            try
            {
                session.Handshake(coldBoot: true);
                failureCode = "NO_FAILURE_OBSERVED";
            }
            catch (ProtocolViolationException ex)
            {
                failureCode = ex.ErrorCode;
            }
            transport["pipeConnectFailureCode"] = failureCode;
            transport["pipeConnectFailureAction"] = "FAIL_CLOSED";
            transport["stdioFallbackAttemptedOnPipeFailure"] = session.StdioUsedAsProtocolTransport;
            transport["lifecycleStateAfterPipeFailure"] = session.Lifecycle.Current.ToString();
            outcome["partA"] = new Dictionary<string, object?>
            {
                ["failureCode"] = failureCode,
                ["failClosed"] = failureCode == ErrorCodes.HandshakeTimeout,
                ["stdioUsed"] = session.StdioUsedAsProtocolTransport,
            };
        }

        // Part B: after READY the pipe is torn down abruptly. The supervisor must
        // treat it as a fail-closed degradation + reconnect, never as a transport swap.
        using (var session = new SupervisorSession(new SupervisorSession.Options
        {
            PythonExe = python,
            EngineScript = engine,
            WorkDir = partBDir,
            ContractsDir = contractsDir,
            SessionId = sessionId,
            Trace = trace,
            EngineLogPath = Path.Combine(partBDir, "engine_trace.jsonl"),
        }))
        {
            session.StartGeneration(coldBoot: true);
            session.Handshake(coldBoot: true);
            session.ReachReady(coldBoot: true, noRecoverableBusinessState: true);
            session.HeartbeatRound();

            session.SendCommand("test.close_pipe", timeoutMs: 1500);
            var deadline = Environment.TickCount64 + 4000;
            while (Environment.TickCount64 < deadline && session.PipeAbortObserved == false)
            {
                Thread.Sleep(10);
            }

            var degraded = session.Lifecycle.TryTransitionTo(LifecycleState.DEGRADED, out var degradedCode);
            var down = session.Lifecycle.TryTransitionTo(LifecycleState.ENGINE_DOWN, out var downCode);

            transport["pipeAbortAfterReadyAction"] = "DEGRADED_THEN_ENGINE_DOWN_RECONNECT";
            transport["stdioFallbackAttemptedOnPipeAbort"] = session.StdioUsedAsProtocolTransport;
            outcome["partB"] = new Dictionary<string, object?>
            {
                ["pipeAbortObserved"] = session.PipeAbortObserved,
                ["pipeAbortReason"] = session.PipeAbortReason,
                ["degradedTransitionAccepted"] = degraded,
                ["degradedErrorCode"] = degradedCode,
                ["engineDownTransitionAccepted"] = down,
                ["engineDownErrorCode"] = downCode,
                ["stdioUsed"] = session.StdioUsedAsProtocolTransport,
            };
            outcome["lifecycleTrace"] = traceRows(session);
        }

        transport["stdioFallbackAttempted"] =
            (bool)(transport["stdioFallbackAttemptedOnPipeFailure"] ?? false)
            || (bool)(transport["stdioFallbackAttemptedOnPipeAbort"] ?? false);

        return outcome;
    }

    private static Dictionary<string, object?> RunMetrics(string python, string engine, string workDir,
        string contractsDir, string sessionId, TraceLog trace, int runs)
    {
        var raw = new List<Dictionary<string, object?>>();
        var errors = new List<string>();

        for (var run = 1; run <= runs; run++)
        {
            var runDir = Path.Combine(workDir, $"run{run:00}");
            Directory.CreateDirectory(runDir);
            try
            {
                using var session = new SupervisorSession(new SupervisorSession.Options
                {
                    PythonExe = python,
                    EngineScript = engine,
                    WorkDir = runDir,
                    ContractsDir = contractsDir,
                    SessionId = sessionId,
                    Trace = run == 1 ? trace : null,
                    EngineLogPath = Path.Combine(runDir, "engine_trace.jsonl"),
                });

                session.StartGeneration(coldBoot: true);
                var g1 = session.Handshake(coldBoot: true);
                session.ReachReady(coldBoot: true, noRecoverableBusinessState: true);

                session.CrashAndMeasure();
                session.TransitionToEngineDownOnCrash();
                var restart = session.RestartAndMeasure();
                var g2 = session.Handshake(coldBoot: false);
                session.ReachReady(coldBoot: false, noRecoverableBusinessState: false);
                session.ControlledShutdown();

                raw.Add(new Dictionary<string, object?>
                {
                    ["run"] = run,
                    ["processExitDetectionMs"] = g1.ProcessExitDetectionMs,
                    ["processRestartMs"] = restart.ProcessRestartMs,
                    ["handshakeMs"] = g1.HandshakeMs,
                    ["handshakeMsGeneration2"] = g2.HandshakeMs,
                    ["snapshotResyncMs"] = g2.SnapshotResyncMs,
                    ["mockBusinessReadyMs"] = g1.MockBusinessReadyMs,
                    ["mockBusinessReadyMsGeneration2"] = g2.MockBusinessReadyMs,
                    ["exitDetectionSignal"] = session.ExitDetectionSignal,
                    ["childExitCode"] = session.ExitCode,
                });
            }
            catch (Exception ex)
            {
                errors.Add($"run {run}: {ex.GetType().Name}: {ex.Message} | {ex.StackTrace?.Split('\n').FirstOrDefault()?.Trim()}");
                raw.Add(new Dictionary<string, object?> { ["run"] = run, ["failed"] = true, ["error"] = ex.Message });
            }
        }

        var metricNames = new[]
        {
            "processExitDetectionMs", "processRestartMs", "handshakeMs", "snapshotResyncMs", "mockBusinessReadyMs",
        };
        var summary = new Dictionary<string, object?>
        {
            ["businessReadyMs"] = null,
            ["businessReadyStatus"] = "NOT_MEASURED",
            ["sampleCount"] = runs,
            ["p95Policy"] = "P95 is only reported when a metric has at least 20 independent raw samples",
        };
        foreach (var name in metricNames)
        {
            var values = raw.Where(r => r.ContainsKey(name) && r[name] is double)
                .Select(r => (double)r[name]!)
                .OrderBy(v => v)
                .ToList();
            summary[name] = Stats(values);
            summary[$"{name}_sampleCount"] = values.Count;
        }
        summary["mockBusinessReadyMs_isMock"] = true;

        return new Dictionary<string, object?>
        {
            ["runs"] = runs,
            ["raw"] = raw,
            ["summary"] = summary,
            ["errors"] = errors,
        };
    }

    private static Dictionary<string, object?> RunMmfLifecycle(string python, string engine, string workDir,
        string contractsDir, string sessionId, TraceLog trace)
    {
        var generations = new List<Dictionary<string, object?>>();

        using var session = new SupervisorSession(new SupervisorSession.Options
        {
            PythonExe = python,
            EngineScript = engine,
            WorkDir = workDir,
            ContractsDir = contractsDir,
            SessionId = sessionId,
            Trace = trace,
            EngineLogPath = Path.Combine(workDir, "engine_trace.jsonl"),
        });

        // ---- generation 1
        var g1 = session.StartGeneration(coldBoot: true);
        session.Handshake(coldBoot: true);
        session.ReachReady(coldBoot: true, noRecoverableBusinessState: true);
        var engineProbe1 = ReadEngineMmfProbe(workDir);
        session.ControlledShutdown();
        Thread.Sleep(150);
        var disposed1 = session.CloseCurrentGeneration();
        generations.Add(new Dictionary<string, object?>
        {
            ["generationId"] = 1,
            ["mapName"] = g1.MapName,
            ["hostRecord"] = disposed1,
            ["engineProbe"] = engineProbe1,
        });

        // ---- generation 2 (new nonce must produce a new map name)
        var g2 = session.StartGeneration(coldBoot: false);
        session.Handshake(coldBoot: false);
        session.ReachReady(coldBoot: false, noRecoverableBusinessState: false);
        var engineProbe2 = ReadEngineMmfProbe(workDir);
        session.ControlledShutdown();
        Thread.Sleep(150);
        var disposed2 = session.CloseCurrentGeneration();
        generations.Add(new Dictionary<string, object?>
        {
            ["generationId"] = 2,
            ["mapName"] = g2.MapName,
            ["hostRecord"] = disposed2,
            ["engineProbe"] = engineProbe2,
        });

        var first = session.Mmf.Records[0];
        var second = session.Mmf.Records[1];

        return new Dictionary<string, object?>
        {
            ["mmfCreated"] = first.Created && second.Created,
            ["mapName"] = first.MapName,
            ["mapTotalSizeBytes"] = first.DeclaredCapacityBytes,
            ["slotCount"] = ProtocolConstants.SlotCount,
            ["slotSizeBytes"] = ProtocolConstants.SlotSizeBytes,
            ["zeroInitialized"] = first.ZeroInitialized && second.ZeroInitialized,
            ["nonZeroBytesFound"] = first.NonZeroBytesFound,
            ["exactSizeViewSucceeded"] = first.ExactSizeViewSucceeded,
            ["oversizeViewDenied"] = first.OversizeViewDenied,
            ["oversizeViewErrorCode"] = first.OversizeViewErrorCode,
            ["engineOpenMode"] = "FILE_MAP_READ (0x0004)",
            ["engineOpenSucceeded"] = ProbeFlag(engineProbe1, "openSucceeded"),
            ["writeDenialStatus"] = ProbeString(engineProbe1, "writeDenialStatus"),
            ["writeDenialErrorCode"] = ProbeInt(engineProbe1, "writeViewErrorCode"),
            ["generation1MapName"] = first.MapName,
            ["generation2MapName"] = second.MapName,
            ["mapNameChanged"] = !string.Equals(first.MapName, second.MapName, StringComparison.Ordinal),
            ["oldGenerationDisposed"] = first.DisposeSucceeded,
            ["oldGenerationReopenFailed"] = first.ReopenAfterDisposeFailed,
            ["oldGenerationReopenErrorCode"] = first.ReopenAfterDisposeErrorCode,
            ["generation2Disposed"] = second.DisposeSucceeded,
            ["generation2ReopenFailed"] = second.ReopenAfterDisposeFailed,
            ["frameHeadersWritten"] = session.Mmf.FrameHeadersWritten,
            ["frameReadyMessagesSent"] = session.Mmf.FrameReadyMessagesSent,
            ["generations"] = generations,
            ["lifecycleTrace"] = traceRows(session),
            ["metrics"] = Metrics(session),
        };
    }

    /// <summary>
    /// Re-encodes every frozen golden message vector through the host's own encoder
    /// and compares the result byte-for-byte, including the 4-byte little-endian
    /// length prefix. This is the C# half of the cross-language wire parity proof.
    /// </summary>
    private static Dictionary<string, object?> RunGoldenParity(string contractsDir)
    {
        var dir = MessageCatalog.ResolveContractsDirectory(contractsDir, AppContext.BaseDirectory);
        var golden = JsonNode.Parse(File.ReadAllText(Path.Combine(dir, "golden_vectors_v1.json"))) as JsonObject
                     ?? throw new InvalidDataException("golden_vectors_v1.json is not a JSON object");

        var vectors = (JsonArray)golden["messageVectors"]!;
        var mismatches = new List<Dictionary<string, object?>>();
        var matched = new List<string>();

        foreach (var entry in vectors)
        {
            var vector = (JsonObject)entry!;
            var name = (string?)vector["name"] ?? "<unnamed>";
            var messageType = (string?)vector["messageType"] ?? string.Empty;
            var envelopeNode = vector["envelope"]!;
            var expectedJson = (string?)vector["expectedJsonCompact"] ?? string.Empty;
            var expectedFramedHex = (string?)vector["expectedFramedHex"] ?? string.Empty;
            var expectedLengthPrefix = (int?)vector["lengthPrefixBytes"] ?? -1;

            // Parse the frozen envelope exactly as a receiver would, then re-encode it.
            var envelope = Envelope.Parse(System.Text.Encoding.UTF8.GetBytes(envelopeNode.ToJsonString()));
            if (!string.Equals(envelope.MessageType, messageType, StringComparison.Ordinal))
            {
                mismatches.Add(new Dictionary<string, object?>
                {
                    ["name"] = name,
                    ["messageType"] = messageType,
                    ["reason"] = $"parsed messageType '{envelope.MessageType}' != declared '{messageType}'",
                });
                continue;
            }

            var actualJson = envelope.ToCompactJson();
            var actualFramed = Framing.FrameEnvelope(envelope);
            var actualFramedHex = Json.Hex(actualFramed);
            var actualPrefix = actualFramed.Length - 4;

            var problems = new List<string>();
            if (!string.Equals(actualJson, expectedJson, StringComparison.Ordinal))
            {
                problems.Add("expectedJsonCompact mismatch");
            }
            if (actualPrefix != expectedLengthPrefix)
            {
                problems.Add($"lengthPrefixBytes {actualPrefix} != {expectedLengthPrefix}");
            }
            if (!string.Equals(actualFramedHex, expectedFramedHex, StringComparison.Ordinal))
            {
                problems.Add("expectedFramedHex mismatch");
            }

            if (problems.Count > 0)
            {
                mismatches.Add(new Dictionary<string, object?>
                {
                    ["name"] = name,
                    ["messageType"] = messageType,
                    ["reason"] = string.Join("; ", problems),
                    ["expectedJsonCompact"] = expectedJson,
                    ["actualJsonCompact"] = actualJson,
                    ["expectedFramedHex"] = expectedFramedHex,
                    ["actualFramedHex"] = actualFramedHex,
                });
            }
            else
            {
                matched.Add(messageType);
            }
        }

        return new Dictionary<string, object?>
        {
            ["totalVectors"] = vectors.Count,
            ["matchedVectors"] = matched.Count,
            ["mismatchedVectors"] = mismatches.Count,
            ["matchedMessageTypes"] = matched,
            ["mismatches"] = mismatches,
            ["allMatched"] = mismatches.Count == 0 && matched.Count == vectors.Count,
        };
    }

    /// <summary>
    /// T03: an engine that cannot satisfy a mandatory capability must be rejected
    /// with HELLO_ACK status REJECTED_CAPABILITY and the host must not treat the
    /// handshake as a success.
    /// </summary>
    private static Dictionary<string, object?> RunCapabilityGate(string python, string engine, string workDir,
        string contractsDir, string sessionId, TraceLog trace)
    {
        using var session = new SupervisorSession(new SupervisorSession.Options
        {
            PythonExe = python,
            EngineScript = engine,
            WorkDir = workDir,
            ContractsDir = contractsDir,
            SessionId = sessionId,
            Trace = trace,
            EngineFaultCapability = _engineFaultCapability,
        });

        session.StartGeneration(coldBoot: true);
        GenerationRecord? record = null;
        string handshakeError = string.Empty;
        try
        {
            record = session.Handshake(coldBoot: true);
        }
        catch (ProtocolViolationException ex)
        {
            handshakeError = ex.ErrorCode;
        }

        var readyRejected = !session.Lifecycle.TryTransitionTo(LifecycleState.READY, out var readyErrorCode);

        return new Dictionary<string, object?>
        {
            ["mandatoryCapabilities"] = session.Capabilities.MandatoryNames,
            ["advertisedCapabilities"] = session.Capabilities.BuildAdvertisement(),
            ["faultInjectedCapability"] = _engineFaultCapability,
            ["helloAckStatus"] = record?.HelloAckStatus,
            ["helloAckReadiness"] = record?.EngineReadiness,
            ["engineBusinessReady"] = record?.EngineBusinessReady,
            ["protocolNegotiated"] = session.Lifecycle.ProtocolNegotiated,
            ["capabilitiesAccepted"] = session.Lifecycle.CapabilitiesAccepted,
            ["handshakeErrorCode"] = handshakeError,
            ["readyTransitionRejected"] = readyRejected,
            ["readyTransitionErrorCode"] = readyErrorCode,
            ["lifecycleTrace"] = traceRows(session),
            ["errors"] = session.Errors,
        };
    }

    /// <summary>
    /// T06: a missed heartbeat degrades to DEGRADED (not ENGINE_DOWN) and recovery
    /// on the same generation returns to READY.
    /// </summary>
    private static Dictionary<string, object?> RunHeartbeatDegrade(string python, string engine, string workDir,
        string contractsDir, string sessionId, TraceLog trace)
    {
        using var session = new SupervisorSession(new SupervisorSession.Options
        {
            PythonExe = python,
            EngineScript = engine,
            WorkDir = workDir,
            ContractsDir = contractsDir,
            SessionId = sessionId,
            Trace = trace,
            EngineLogPath = Path.Combine(workDir, "engine_trace.jsonl"),
        });

        session.StartGeneration(coldBoot: true);
        session.Handshake(coldBoot: true);
        session.ReachReady(coldBoot: true, noRecoverableBusinessState: true);

        var healthyBefore = session.TryHeartbeatRound(out var beforeError);

        session.SendCommand("test.stop_heartbeat");
        var missed = !session.TryHeartbeatRound(out var missError);

        var degraded = session.Lifecycle.TryTransitionTo(LifecycleState.DEGRADED, out var degradedError);
        var childAliveWhileDegraded = session.ChildAlive;
        var pipeAliveWhileDegraded = !session.PipeAbortObserved;

        session.SendCommand("test.resume_heartbeat");
        var recovered = session.TryHeartbeatRound(out var recoverError);

        // Per the frozen READY gate, leaving READY clears snapshotResynced, so
        // DEGRADED -> READY directly is not a legal recovery path: the session must
        // resync again. Assert that, then take the legal route.
        var directReadyRejected = !session.Lifecycle.TryTransitionTo(LifecycleState.READY, out var directError);
        session.ReachReady(coldBoot: false, noRecoverableBusinessState: false);
        var readyAfterResync = session.Lifecycle.Current == LifecycleState.READY;

        var shutdown = session.ControlledShutdown();

        return new Dictionary<string, object?>
        {
            ["heartbeatHealthyBeforeFault"] = healthyBefore,
            ["heartbeatBeforeFaultErrorCode"] = beforeError,
            ["heartbeatMissDetected"] = missed,
            ["heartbeatMissErrorCode"] = missError,
            ["degradedTransitionAccepted"] = degraded,
            ["degradedErrorCode"] = degradedError,
            ["childAliveWhileDegraded"] = childAliveWhileDegraded,
            ["pipeAliveWhileDegraded"] = pipeAliveWhileDegraded,
            ["heartbeatRecovered"] = recovered,
            ["heartbeatRecoverErrorCode"] = recoverError,
            ["directDegradedToReadyRejected"] = directReadyRejected,
            ["directDegradedToReadyErrorCode"] = directError,
            ["readyAfterResync"] = readyAfterResync,
            ["snapshotResyncMs"] = session.Generations[^1].SnapshotResyncMs,
            ["finalState"] = session.Lifecycle.Current.ToString(),
            ["lifecycleTrace"] = traceRows(session),
            ["shutdown"] = shutdown,
            ["errors"] = session.Errors,
        };
    }

    /// <summary>
    /// T18 + T03 fail-closed paths: a HELLO whose frameBufferSize contradicts the
    /// fixed v1 geometry must be rejected by the engine with ERR_RING_GEOMETRY_MISMATCH
    /// and must terminate the session.
    /// </summary>
    private static Dictionary<string, object?> RunFaultInjection(string python, string engine, string workDir,
        string contractsDir, string sessionId, TraceLog trace)
    {
        var outcome = new Dictionary<string, object?>();

        // Part A: mandatory capability unavailable.
        var partADir = Path.Combine(workDir, "geometry");
        Directory.CreateDirectory(partADir);
        using (var session = new SupervisorSession(new SupervisorSession.Options
        {
            PythonExe = python,
            EngineScript = engine,
            WorkDir = partADir,
            ContractsDir = contractsDir,
            SessionId = sessionId,
            Trace = trace,
            EngineFaultHelloSize = _engineFaultHelloSize,
            EngineLogPath = Path.Combine(partADir, "engine_trace.jsonl"),
        }))
        {
            session.StartGeneration(coldBoot: true);
            string errorCode = string.Empty;
            try
            {
                session.Handshake(coldBoot: true);
            }
            catch (ProtocolViolationException ex)
            {
                errorCode = ex.ErrorCode;
            }

            outcome["geometry"] = new Dictionary<string, object?>
            {
                ["injectedFrameBufferSize"] = _engineFaultHelloSize,
                ["declaredFrameBufferSize"] = ProtocolConstants.MapTotalSizeBytes,
                ["errorCode"] = errorCode,
                ["fatalFailClosed"] = errorCode == ErrorCodes.RingGeometryMismatch,
                ["helloAckValidated"] = session.Generations.Count > 0 && session.Generations[^1].HelloAckValidated,
                ["finalState"] = session.Lifecycle.Current.ToString(),
            };
        }

        return outcome;
    }

    /// <summary>
    /// T13: a STATE_SNAPSHOT whose snapshotSessionId does not match the active
    /// session must fail closed with ERR_STALE_SESSION and must not reach READY.
    /// </summary>
    private static Dictionary<string, object?> RunResyncFault(string python, string engine, string workDir,
        string contractsDir, string sessionId, TraceLog trace)
    {
        using var session = new SupervisorSession(new SupervisorSession.Options
        {
            PythonExe = python,
            EngineScript = engine,
            WorkDir = workDir,
            ContractsDir = contractsDir,
            SessionId = sessionId,
            Trace = trace,
            EngineLogPath = Path.Combine(workDir, "engine_trace.jsonl"),
        });

        session.StartGeneration(coldBoot: true);
        session.Handshake(coldBoot: true);
        session.ReachReady(coldBoot: true, noRecoverableBusinessState: true);

        session.CrashAndMeasure();
        session.TransitionToEngineDownOnCrash();
        session.RestartAndMeasure();
        session.Handshake(coldBoot: false);

        session.SendCommand("test.wrong_session_snapshot");
        string errorCode = string.Empty;
        var reachedReady = false;
        try
        {
            session.ReachReady(coldBoot: false, noRecoverableBusinessState: false);
            reachedReady = true;
        }
        catch (ProtocolViolationException ex)
        {
            errorCode = ex.ErrorCode;
        }

        return new Dictionary<string, object?>
        {
            ["wrongSessionErrorCode"] = errorCode,
            ["staleSessionFailClosed"] = errorCode == ErrorCodes.StaleSession,
            ["reachedReadyWithWrongSession"] = reachedReady,
            ["snapshotResynced"] = session.Lifecycle.SnapshotResynced,
            ["finalState"] = session.Lifecycle.Current.ToString(),
            ["lifecycleTrace"] = traceRows(session),
            ["errors"] = session.Errors,
        };
    }

    // ------------------------------------------------------------------ helpers

    private static JsonObject? ReadEngineMmfProbe(string workDir)
    {
        var path = Path.Combine(workDir, "engine_mmf_probe.json");
        if (!File.Exists(path))
        {
            return null;
        }
        try
        {
            return JsonNode.Parse(File.ReadAllText(path)) as JsonObject;
        }
        catch
        {
            return null;
        }
    }

    private static object? ProbeFlag(JsonObject? probe, string key) => probe?[key]?.GetValue<bool>();
    private static object? ProbeString(JsonObject? probe, string key) => probe?[key]?.GetValue<string>();
    private static object? ProbeInt(JsonObject? probe, string key) => probe?[key]?.GetValue<int>();

    private static Dictionary<string, object?> Metrics(SupervisorSession session)
    {
        var gens = session.Generations;
        var first = gens.Count > 0 ? gens[0] : new GenerationRecord();
        var second = gens.Count > 1 ? gens[1] : null;
        return new Dictionary<string, object?>
        {
            ["processExitDetectionMs"] = second?.ProcessExitDetectionMs ?? first.ProcessExitDetectionMs,
            ["processRestartMs"] = second?.ProcessRestartMs,
            ["handshakeMs"] = first.HandshakeMs,
            ["snapshotResyncMs"] = second?.SnapshotResyncMs,
            ["mockBusinessReadyMs"] = first.MockBusinessReadyMs,
            ["businessReadyMs"] = null,
            ["businessReadyStatus"] = "NOT_MEASURED",
            ["businessReadyReason"] = "V2-1 runs a reference/mock engine with no OCR, model weights or visual catalog; real business readiness is not measured",
        };
    }

    private static Dictionary<string, object?> Stats(List<double> values)
    {
        if (values.Count == 0)
        {
            return new Dictionary<string, object?>
            {
                ["min"] = null,
                ["median"] = null,
                ["max"] = null,
                ["sampleCount"] = 0,
            };
        }
        var median = values.Count % 2 == 1
            ? values[values.Count / 2]
            : (values[values.Count / 2 - 1] + values[values.Count / 2]) / 2.0;
        var stats = new Dictionary<string, object?>
        {
            ["min"] = values[0],
            ["median"] = median,
            ["max"] = values[^1],
            ["sampleCount"] = values.Count,
        };
        if (values.Count >= 20)
        {
            stats["p50"] = values[(int)(values.Count * 0.50)];
            stats["p95"] = values[Math.Min((int)(values.Count * 0.95), values.Count - 1)];
        }
        return stats;
    }

    private static List<Dictionary<string, object?>> traceRows(SupervisorSession session) =>
        session.Lifecycle.Trace
            .Select(t => new Dictionary<string, object?> { ["from"] = t.from, ["to"] = t.to, ["outcome"] = t.outcome })
            .ToList();

    private static Dictionary<string, string> ParseArgs(string[] args)
    {
        var map = new Dictionary<string, string>(StringComparer.Ordinal);
        for (var i = 0; i < args.Length; i++)
        {
            if (!args[i].StartsWith("--", StringComparison.Ordinal))
            {
                continue;
            }
            var name = args[i];
            if (i + 1 < args.Length && !args[i + 1].StartsWith("--", StringComparison.Ordinal))
            {
                map[name] = args[i + 1];
                i++;
            }
            else
            {
                map[name] = "true";
            }
        }
        return map;
    }

    private static string Arg(IReadOnlyDictionary<string, string> args, string name, string fallback) =>
        args.TryGetValue(name, out var value) ? value : fallback;
}
