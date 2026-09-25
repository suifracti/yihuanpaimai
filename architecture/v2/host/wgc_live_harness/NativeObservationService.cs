using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading;
using NteHost;
using NteHost.Protocol;
using NteHost.WindowMonitor;

namespace WgcLiveHarness;

/// <summary>
/// The opt-in Native observation profile used by the existing Python Main/HUD
/// entry. It owns one target monitor, one WGC capture, one Host supervisor and
/// one real Python business Engine. The process exits on a safety pause; the
/// UI must explicitly start a new observation session before frames can flow
/// again. That makes a focus/identity/scene boundary a session boundary too.
/// </summary>
internal static class NativeObservationService
{
    private static readonly JsonSerializerOptions JsonLineOptions = new()
    {
        WriteIndented = false,
        Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
    };

    public static int Run(string[] args)
    {
        var repoRoot = FindRepoRoot(Arg(args, "--repo", Directory.GetCurrentDirectory()));
        var specImage = Arg(args, "--spec-image", "htgame.exe");
        var specClass = Arg(args, "--spec-class", "UnrealWindow");
        var pythonArg = Arg(args, "--python", "python");
        var pythonExe = Path.IsPathRooted(pythonArg) ? Path.GetFullPath(pythonArg) : pythonArg;
        var targetWaitMs = ParseInt(args, "--target-wait-ms", 15000);
        var frameWaitMs = ParseInt(args, "--frame-wait-ms", 5000);
        var intervalMs = Math.Max(25, ParseInt(args, "--frame-interval-ms", 120));
        var maxFrames = ParseInt(args, "--max-frames", 0);
        var workDir = Path.GetFullPath(Arg(
            args,
            "--work-dir",
            Path.Combine(repoRoot, "build", "native-observation", $"session-{Guid.NewGuid():N}")));
        var engineScript = Path.GetFullPath(Arg(
            args,
            "--engine",
            Path.Combine(repoRoot, "architecture", "v2", "host", "engine_v22", "nte_engine_v22.py")));
        var contractsDir = Path.Combine(repoRoot, "architecture", "v2", "contracts");
        var catalogPath = Path.Combine(repoRoot, "assets", "catalog_065.json");
        Directory.CreateDirectory(workDir);

        var sessionId = $"native-live-{Guid.NewGuid():N}";
        var tracePath = Path.Combine(workDir, "host-trace.jsonl");
        var engineLogPath = Path.Combine(workDir, "engine-trace.jsonl");
        var controlQueue = new BlockingCollection<JsonObject>();
        StartControlReader(controlQueue);

        EmitStatus(sessionId, "STARTING", "explicit-start", new
        {
            profile = "native-readonly-v1",
            workDir,
            engine = engineScript,
            inputActions = false,
            formalHistoryWriter = false,
        });

        try
        {
            using var monitor = new WindowMonitor(new WindowMonitorOptions
            {
                Spec = new TargetWindowSpec(specImage, specClass),
                RequireVisible = true,
                SkipOwnProcessInHook = true,
                EventQueueCapacity = 4096,
            });
            monitor.Start();

            var target = WaitForTarget(monitor, targetWaitMs);
            if (!IsUsableTarget(target))
            {
                EmitStatus(sessionId, "ERROR", "target-not-found", TargetEvidence(target));
                return 2;
            }

            var resumePath = Path.Combine(workDir, "resume-state.json");
            if (File.Exists(resumePath))
            {
                var resume = ReadJsonObject(resumePath)!;
                var identity = resume["target"]?["identity"];
                if (identity is null
                    || (long?)identity["Hwnd"] != target.TargetHwnd
                    || (int?)identity["Pid"] != target.TargetPid
                    || (long?)identity["ProcessInstanceToken"] != target.TargetIdentity?.ProcessInstanceToken)
                    throw new InvalidOperationException("resume-target-identity-mismatch: start a new match explicitly");
                File.WriteAllText(Path.Combine(workDir, "engine_state.json"), resume.ToJsonString());
            }
            using var capture = new WgcWindowCapture(new IntPtr(target.TargetHwnd));
            using var trace = new TraceLog(tracePath, sessionId, "bootstrap");
            using var session = new SupervisorSession(new SupervisorSession.Options
            {
                PythonExe = pythonExe,
                EngineScript = engineScript,
                WorkDir = workDir,
                ContractsDir = contractsDir,
                SessionId = sessionId,
                Trace = trace,
                EngineLogPath = engineLogPath,
                DataOrigin = "live-trial",
                CatalogPath = catalogPath,
                EnableFrameTransport = true,
                AcceptTimeoutMs = 15000,
            });

            session.StartGeneration(coldBoot: true);
            var handshake = session.Handshake(coldBoot: true);
            session.ReachReady(coldBoot: true, noRecoverableBusinessState: true);
            EmitStatus(sessionId, "READY", "engine-ready", new
            {
                target = TargetEvidence(target),
                engineReadiness = handshake.EngineReadiness,
                engineBusinessReady = handshake.EngineBusinessReady,
                generation = session.GenerationId,
                geometry = ProtocolConstants.FixedGeometry(),
                captureItem = new { width = capture.CaptureItemWidth, height = capture.CaptureItemHeight },
                customerArea = new
                {
                    width = capture.Width,
                    height = capture.Height,
                    offsetX = capture.ClientOffsetX,
                    offsetY = capture.ClientOffsetY,
                },
                inputActions = false,
                formalHistoryWriter = false,
            });

            var acceptedFrames = 0;
            var firstFrameWritten = false;
            while (maxFrames <= 0 || acceptedFrames < maxFrames)
            {
                if (DrainControls(controlQueue, session, sessionId, monitor, target))
                {
                    session.ControlledShutdown();
                    EmitStatus(sessionId, "STOPPED", "explicit-stop", new { acceptedFrames });
                    return 0;
                }
                var beforeCapture = monitor.Snapshot();
                if (!IsUsableTarget(beforeCapture) || beforeCapture.TargetHwnd != target.TargetHwnd
                    || beforeCapture.Generation != target.Generation)
                {
                    EmitStatus(sessionId, "PAUSED", PauseReason(beforeCapture), TargetEvidence(beforeCapture));
                    session.ControlledShutdown();
                    return 3;
                }

                CapturedBgraFrame frame;
                try
                {
                    frame = capture.Capture(frameWaitMs);
                }
                catch (Exception ex)
                {
                    EmitStatus(sessionId, "PAUSED", "capture-failed", new
                    {
                        error = $"{ex.GetType().Name}: {ex.Message}",
                        stackTrace = ex.StackTrace,
                        target = TargetEvidence(beforeCapture),
                    });
                    session.ControlledShutdown();
                    return 4;
                }

                var afterCapture = monitor.Snapshot();
                if (!IsUsableTarget(afterCapture) || afterCapture.TargetHwnd != target.TargetHwnd
                    || afterCapture.Generation != target.Generation)
                {
                    EmitStatus(sessionId, "PAUSED", PauseReason(afterCapture), TargetEvidence(afterCapture));
                    session.ControlledShutdown();
                    return 3;
                }

                Dictionary<string, object?> transfer;
                try
                {
                    transfer = session.SendFrame(
                        frame.Pixels,
                        frame.Width,
                        frame.Height,
                        frame.Stride,
                        frame.CaptureTimestampNs,
                        timeoutMs: 30000);
                }
                catch (Exception ex)
                {
                    EmitStatus(sessionId, "ERROR", "engine-frame-failed", new
                    {
                        error = $"{ex.GetType().Name}: {ex.Message}",
                        capturedAtNs = frame.CaptureTimestampNs,
                        capturedAtUtc = frame.CapturedAtUtc,
                    });
                    session.ControlledShutdown();
                    return 5;
                }

                if (transfer.TryGetValue("perceptionReceived", out var received) && received is not true)
                {
                    EmitStatus(sessionId, "ERROR", "perception-not-received", transfer);
                    session.ControlledShutdown();
                    return 6;
                }

                var afterEngine = monitor.Snapshot();
                if (!IsUsableTarget(afterEngine) || afterEngine.TargetHwnd != target.TargetHwnd
                    || afterEngine.Generation != target.Generation)
                {
                    // A result that completed after a target boundary is not
                    // allowed to become the next observation's HUD state.
                    EmitStatus(sessionId, "PAUSED", PauseReason(afterEngine), TargetEvidence(afterEngine));
                    session.ControlledShutdown();
                    return 3;
                }

                var state = ReadJsonObject(Path.Combine(workDir, "engine_state.json"));
                var perception = transfer.TryGetValue("perceptionPayload", out var payload)
                    ? payload as JsonObject
                    : null;
                var scene = (string?)perception?["scene"] ?? "UNKNOWN";
                var frameSequence = Convert.ToInt64(transfer.GetValueOrDefault("sequence") ?? 0);

                if (scene is "SETTLEMENT" or "AUCTION_LOBBY" or "CITY_TYCOON_HUB"
                    or "CITY_LEISURE_MENU" or "OPEN_WORLD" or "UNKNOWN")
                {
                    // Preserve the exact frame that caused the boundary.  A
                    // hash in frame_records is not enough to distinguish a
                    // real game transition from a scene-classification error.
                    var boundaryRawPath = Path.Combine(workDir, "boundary-frame.bmp");
                    var boundaryStatePath = Path.Combine(workDir, "boundary-frame-state.json");
                    string? boundaryEvidenceError = null;
                    try
                    {
                        WriteBmp(boundaryRawPath, frame.Width, frame.Height, frame.Pixels);
                        File.WriteAllText(boundaryStatePath,
                            JsonSerializer.Serialize(new
                            {
                                frameSequence,
                                frame.CaptureTimestampNs,
                                frame.CapturedAtUtc,
                                scene,
                                state,
                                perception,
                            }, JsonLineOptions));
                    }
                    catch (Exception evidenceEx)
                    {
                        boundaryEvidenceError = $"{evidenceEx.GetType().Name}: {evidenceEx.Message}";
                    }
                    EmitStatus(sessionId, "PAUSED", $"scene-boundary:{scene}", new
                    {
                        scene,
                        frameSequence,
                        capturedAtNs = frame.CaptureTimestampNs,
                        capturedAtUtc = frame.CapturedAtUtc,
                        boundaryRawPath = boundaryEvidenceError is null ? boundaryRawPath : null,
                        boundaryStatePath = boundaryEvidenceError is null ? boundaryStatePath : null,
                        boundaryEvidenceError,
                        target = TargetEvidence(afterEngine),
                    });
                    session.ControlledShutdown();
                    return 7;
                }

                if (!firstFrameWritten)
                {
                    WriteBmp(Path.Combine(workDir, "first-frame.bmp"), frame.Width, frame.Height, frame.Pixels);
                    File.WriteAllText(Path.Combine(workDir, "first-frame-state.json"),
                        JsonSerializer.Serialize(new { frameSequence, frame.CaptureTimestampNs, state }, JsonLineOptions));
                    firstFrameWritten = true;
                }

                // Bounded paired evidence: first and latest accepted business
                // frame, not a recording of every game frame.
                var latestRawPath = Path.Combine(workDir, "latest-business-frame.bmp");
                WriteBmp(latestRawPath, frame.Width, frame.Height, frame.Pixels);
                File.WriteAllText(Path.Combine(workDir, "latest-business-state.json"),
                    JsonSerializer.Serialize(new { frameSequence, frame.CaptureTimestampNs, state }, JsonLineOptions));

                acceptedFrames++;
                EmitObservation(
                    sessionId,
                    afterEngine,
                    frame,
                    transfer,
                state,
                acceptedFrames,
                    latestRawPath,
                    capture);
                Thread.Sleep(intervalMs);
            }

            session.ControlledShutdown();
            EmitStatus(sessionId, "STOPPED", "frame-limit", new { acceptedFrames });
            return 0;
        }
        catch (Exception ex)
        {
            EmitStatus(sessionId, "ERROR", "native-observation-failed", new
            {
                error = $"{ex.GetType().Name}: {ex.Message}",
                stackTrace = ex.StackTrace,
                inputActions = false,
                formalHistoryWriter = false,
            });
            return 1;
        }
    }

    private static void EmitObservation(
        string sessionId,
        WindowMonitorSnapshot target,
        CapturedBgraFrame frame,
        IReadOnlyDictionary<string, object?> transfer,
        JsonObject? state,
        int acceptedFrames,
        string rawFramePath,
        WgcWindowCapture capture)
    {
        var line = new JsonObject
        {
            ["type"] = "native_observation",
            ["schemaVersion"] = "native-observation-v1",
            ["status"] = "FRAME",
            ["observationSessionId"] = sessionId,
            ["sourceKind"] = "native_wgc",
            ["inputActions"] = false,
            ["formalHistoryWriter"] = false,
            ["acceptedFrameCount"] = acceptedFrames,
            ["target"] = JsonSerializer.SerializeToNode(TargetEvidence(target), JsonLineOptions),
            ["frame"] = new JsonObject
            {
                ["sequence"] = Convert.ToInt64(transfer.GetValueOrDefault("sequence") ?? 0),
                ["capturedAtNs"] = frame.CaptureTimestampNs,
                ["capturedAtUtc"] = frame.CapturedAtUtc,
                ["width"] = frame.Width,
                ["height"] = frame.Height,
                ["stride"] = frame.Stride,
                ["captureItemWidth"] = capture.CaptureItemWidth,
                ["captureItemHeight"] = capture.CaptureItemHeight,
                ["clientOffsetX"] = capture.ClientOffsetX,
                ["clientOffsetY"] = capture.ClientOffsetY,
                ["freshnessMs"] = Math.Max(0.0, (ProtocolClock.NowNs() - frame.CaptureTimestampNs) / 1_000_000.0),
                ["rawFramePath"] = rawFramePath,
            },
            // The received envelope retains ownership of its payload node.
            ["perception"] = (transfer.GetValueOrDefault("perceptionPayload") as JsonObject)?.DeepClone(),
            ["currentMatch"] = state?["currentMatch"]?.DeepClone(),
            ["pipelineContext"] = state?["pipelineContext"]?.DeepClone(),
            ["lastFrame"] = state?["lastFrame"]?.DeepClone(),
        };
        EmitLine(line);
    }

    private static void StartControlReader(BlockingCollection<JsonObject> queue)
    {
        var reader = new Thread(() =>
        {
            try
            {
                while (true)
                {
                    var raw = Console.ReadLine();
                    if (raw is null)
                    {
                        return;
                    }
                    if (JsonNode.Parse(raw) is JsonObject message)
                    {
                        queue.Add(message);
                    }
                }
            }
            catch (Exception)
            {
                // The GUI may close stdin during shutdown.  The Host loop is
                // still responsible for the protocol shutdown and will not
                // infer a new observation frame from an EOF on this control
                // channel.
            }
        })
        {
            IsBackground = true,
            Name = "native-observation-controls",
        };
        reader.Start();
    }

    private static bool DrainControls(
        BlockingCollection<JsonObject> queue,
        SupervisorSession session,
        string sessionId,
        WindowMonitor monitor,
        WindowMonitorSnapshot sessionTarget)
    {
        while (queue.TryTake(out var message))
        {
            var type = (string?)message["type"];
            if (string.Equals(type, "native_stop", StringComparison.Ordinal))
            {
                return true;
            }
            if (!string.Equals(type, "native_control", StringComparison.Ordinal))
            {
                continue;
            }

            var command = message["command"] as JsonObject;
            if (command is null)
            {
                EmitStatus(sessionId, "CONTROL", "invalid-control", new
                {
                    commandStatus = "REJECT",
                    error = "command must be an object",
                });
                continue;
            }

            var revision = (int?)command["revision"] ?? -1;
            var commandId = $"native-control-{revision}";
            var expectedSessionId = (string?)command["expectedObservationSessionId"];
            if (!string.Equals(expectedSessionId, sessionId, StringComparison.Ordinal))
            {
                EmitStatus(sessionId, "CONTROL", "stale-command-session", new
                {
                    commandId,
                    controlRevision = revision,
                    commandStatus = "REJECT",
                    commandMessageType = "NACK",
                    commandResult = new
                    {
                        status = "REJECT",
                        errorDetails = "STALE_OBSERVATION_SESSION",
                        resultData = new { observationSessionId = sessionId },
                    },
                });
                continue;
            }
            var expectedTarget = command["expectedTargetInstance"] as JsonObject;
            var activeTarget = monitor.Snapshot();
            if (!MatchesCommandTarget(expectedTarget, activeTarget, sessionTarget))
            {
                EmitStatus(sessionId, "CONTROL", "stale-command-target", new
                {
                    commandId,
                    controlRevision = revision,
                    commandStatus = "REJECT",
                    commandMessageType = "NACK",
                    commandResult = new
                    {
                        status = "REJECT",
                        errorDetails = "STALE_TARGET_INSTANCE",
                        resultData = new
                        {
                            expectedObservationSessionId = sessionId,
                            target = TargetEvidence(activeTarget),
                        },
                    },
                });
                continue;
            }
            var workerAction = (string?)command["workerAction"] ?? "match.apply_control";
            if (workerAction is not ("match.apply_control" or "warehouse.instance_decision"))
            {
                EmitStatus(sessionId, "CONTROL", "unsupported-worker-action", new
                {
                    commandId,
                    controlRevision = revision,
                    commandStatus = "REJECT",
                    commandMessageType = "NACK",
                    commandResult = new
                    {
                        status = "REJECT",
                        errorDetails = "UNSUPPORTED_WORKER_ACTION",
                        resultData = new { workerAction },
                    },
                });
                continue;
            }
            try
            {
                var result = session.SendCommandWithId(
                    commandId,
                    workerAction,
                    command.DeepClone() as JsonObject,
                    timeoutMs: 5000);
                EmitStatus(sessionId, "CONTROL", "command-result", new
                {
                    commandId,
                    controlRevision = revision,
                    commandMessageType = result.MessageType,
                    commandStatus = (string?)result.Payload["status"],
                    commandResult = result.Payload.DeepClone(),
                });
            }
            catch (Exception ex)
            {
                EmitStatus(sessionId, "CONTROL", "command-failed", new
                {
                    commandId,
                    controlRevision = revision,
                    commandStatus = "ERROR",
                    error = $"{ex.GetType().Name}: {ex.Message}",
                });
            }
        }
        return false;
    }

    private static bool MatchesCommandTarget(
        JsonObject? expected,
        WindowMonitorSnapshot active,
        WindowMonitorSnapshot sessionTarget)
    {
        if (expected is null || !IsUsableTarget(active))
        {
            return false;
        }
        var processToken = sessionTarget.TargetIdentity?.ProcessInstanceToken;
        return active.TargetHwnd == sessionTarget.TargetHwnd
            && active.TargetPid == sessionTarget.TargetPid
            && active.Generation == sessionTarget.Generation
            && active.TargetIdentity?.ProcessInstanceToken == processToken
            && (long?)expected["targetHwnd"] == sessionTarget.TargetHwnd
            && (int?)expected["targetPid"] == sessionTarget.TargetPid
            && (long?)expected["generation"] == sessionTarget.Generation
            && (long?)expected["processInstanceToken"] == processToken;
    }

    private static void EmitStatus(string sessionId, string status, string reason, object? details)
    {
        var line = new JsonObject
        {
            ["type"] = "native_observation",
            ["schemaVersion"] = "native-observation-v1",
            ["status"] = status,
            ["observationSessionId"] = sessionId,
            ["sourceKind"] = "native_wgc",
            ["reason"] = reason,
            ["inputActions"] = false,
            ["formalHistoryWriter"] = false,
            ["details"] = JsonSerializer.SerializeToNode(details, JsonLineOptions),
        };
        EmitLine(line);
    }

    private static void EmitLine(JsonObject line)
    {
        Console.WriteLine(line.ToJsonString(JsonLineOptions));
        Console.Out.Flush();
    }

    private static WindowMonitorSnapshot WaitForTarget(WindowMonitor monitor, int timeoutMs)
    {
        var deadline = Environment.TickCount64 + timeoutMs;
        var last = monitor.Snapshot();
        while (Environment.TickCount64 < deadline)
        {
            last = monitor.Snapshot();
            if (IsUsableTarget(last))
            {
                return last;
            }
            Thread.Sleep(50);
        }
        return last;
    }

    private static bool IsUsableTarget(WindowMonitorSnapshot snapshot) =>
        snapshot.TargetHwnd != 0
        && snapshot.IsTargetAlive
        && snapshot.IsTargetForeground
        && snapshot.TargetIdentity is { IsPresent: true };

    private static string PauseReason(WindowMonitorSnapshot snapshot)
    {
        if (snapshot.TargetHwnd == 0 || !snapshot.IsTargetAlive)
        {
            return "target-lost";
        }
        if (!snapshot.IsTargetForeground)
        {
            return "focus-lost";
        }
        return "target-identity-changed";
    }

    private static object TargetEvidence(WindowMonitorSnapshot snapshot) => new
    {
        targetHwnd = snapshot.TargetHwnd,
        targetPid = snapshot.TargetPid,
        foregroundHwnd = snapshot.ForegroundHwnd,
        isTargetAlive = snapshot.IsTargetAlive,
        isTargetForeground = snapshot.IsTargetForeground,
        generation = snapshot.Generation,
        observedAtNs = snapshot.ObservedAtNs,
        reason = snapshot.Reason,
        identity = snapshot.TargetIdentity,
    };

    private static JsonObject? ReadJsonObject(string path)
    {
        if (!File.Exists(path))
        {
            return null;
        }
        return JsonNode.Parse(File.ReadAllText(path)) as JsonObject;
    }

    private static int ParseInt(string[] args, string name, int fallback)
    {
        var raw = Arg(args, name, string.Empty);
        return int.TryParse(raw, out var value) ? value : fallback;
    }

    private static string Arg(string[] args, string name, string fallback)
    {
        for (var i = 0; i + 1 < args.Length; i++)
        {
            if (string.Equals(args[i], name, StringComparison.Ordinal))
            {
                return args[i + 1];
            }
        }
        return fallback;
    }

    private static string FindRepoRoot(string start)
    {
        var candidate = Path.GetFullPath(start);
        while (!string.IsNullOrEmpty(candidate))
        {
            if (File.Exists(Path.Combine(candidate, "architecture", "v2", "contracts", "protocol_v1.json")))
            {
                return candidate;
            }
            var parent = Directory.GetParent(candidate)?.FullName;
            if (string.Equals(parent, candidate, StringComparison.OrdinalIgnoreCase))
            {
                break;
            }
            candidate = parent ?? string.Empty;
        }
        throw new DirectoryNotFoundException($"could not locate repository root from '{start}'");
    }

    private static void WriteBmp(string path, int width, int height, byte[] bgra)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path))!);
        using var stream = File.Create(path);
        using var writer = new BinaryWriter(stream, Encoding.UTF8, leaveOpen: false);
        var fileSize = checked(14 + 40 + bgra.Length);
        writer.Write((byte)'B');
        writer.Write((byte)'M');
        writer.Write(fileSize);
        writer.Write((short)0);
        writer.Write((short)0);
        writer.Write(54);
        writer.Write(40);
        writer.Write(width);
        writer.Write(-height);
        writer.Write((short)1);
        writer.Write((short)32);
        writer.Write(0);
        writer.Write(bgra.Length);
        writer.Write(2835);
        writer.Write(2835);
        writer.Write(0);
        writer.Write(0);
        writer.Write(bgra);
    }
}
