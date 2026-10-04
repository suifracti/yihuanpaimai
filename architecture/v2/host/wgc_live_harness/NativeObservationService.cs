using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
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
/// one real Python business Engine. Target/capture safety pauses still end
/// the session, but scene boundaries keep the same read-only observer alive.
/// Main's in-auction gate disables advice until a fresh accepted auction frame.
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
        var sessionId = $"native-live-{Guid.NewGuid():N}";
        var modeOptionIndex = Array.IndexOf(args, "--observation-window-mode");
        var rawObservationWindowMode = modeOptionIndex >= 0 && (modeOptionIndex + 1 >= args.Length
                || args[modeOptionIndex + 1].StartsWith("--", StringComparison.Ordinal))
            ? string.Empty : Arg(args, "--observation-window-mode", BackgroundObservationPolicy.Foreground);
        string observationWindowMode;
        try { observationWindowMode = BackgroundObservationPolicy.ParseMode(rawObservationWindowMode); }
        catch (ArgumentException)
        {
            NativeObservationService.EmitStatus(sessionId, "ERROR", "invalid-observation-window-mode",
                new { requestedMode = rawObservationWindowMode, inputActions = false, formalHistoryWriter = false },
                rawObservationWindowMode);
            return 2;
        }
        // Capture this immutable launch choice; commands cannot change the running session's mode.
        void EmitStatus(string id, string status, string reason, object? details) =>
            NativeObservationService.EmitStatus(id, status, reason, details, observationWindowMode);

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

        var tracePath = Path.Combine(workDir, "host-trace.jsonl");
        var engineLogPath = Path.Combine(workDir, "engine-trace.jsonl");
        var controlQueue = new BlockingCollection<JsonObject>();
        var evidenceQueue = new BlockingCollection<JsonObject>(8);
        Func<WarehouseSourceContext, Func<bool>, bool>? scrollWindow = null;
        using var evidenceLease = new WarehouseEvidenceLease(workDir, sessionId, EmitLine,
            scrollDown: (context, current) => scrollWindow?.Invoke(context, current) == true);
        StartControlReader(controlQueue, evidenceQueue, evidenceLease);

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

            var target = WaitForTarget(monitor, targetWaitMs, observationWindowMode);
            if (!IsObservationTargetUsable(target, observationWindowMode))
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
            File.WriteAllText(Path.Combine(workDir, "observation-target.json"),
                JsonSerializer.Serialize(new
                {
                    observationSessionId = sessionId,
                    targetHwnd = target.TargetHwnd,
                    targetPid = target.TargetPid,
                    targetGeneration = target.Generation,
                    processInstanceToken = target.TargetIdentity!.ProcessInstanceToken,
                    observationWindowMode,
                }, JsonLineOptions));
            using var capture = new WgcWindowCapture(new IntPtr(target.TargetHwnd));
            scrollWindow = (context, current) => WarehouseWindowScroll.SendDown(context, () => current()
                && MatchesObservationTargetIdentity(context.Target, monitor.Snapshot(), target, observationWindowMode)
                && capture.IsClientAreaMappingCurrent());
            if (observationWindowMode == BackgroundObservationPolicy.BackgroundReadOnly
                && !capture.IsClientAreaMappingCurrent())
                throw new InvalidOperationException("background-client-area-mapping-unproven");
            var backgroundDiagnosticLimitBytes = observationWindowMode == BackgroundObservationPolicy.BackgroundReadOnly
                ? 8_388_608L : (long?)null;
            using var trace = new TraceLog(tracePath, sessionId, "bootstrap", maxBytes: backgroundDiagnosticLimitBytes);
            using var session = new SupervisorSession(new SupervisorSession.Options
            {
                PythonExe = pythonExe,
                EngineScript = engineScript,
                WorkDir = workDir,
                ContractsDir = contractsDir,
                SessionId = sessionId,
                Trace = trace,
                EngineLogPath = engineLogPath,
                BackgroundDiagnosticLimitBytes = backgroundDiagnosticLimitBytes,
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
            long lastSourceTimestampNs = 0;
            var firstFrameWritten = false;
            var firstLobbyFrameWritten = false;
            long? unknownSinceMs = null;
            long? settlementSinceMs = null;
            long? settlementSourceDeadlineNs = null;
            var settlementCollectionClosed = false;
            string? settlementMatchId = null;
            while (maxFrames <= 0 || acceptedFrames < maxFrames)
            {
                if (DrainControls(controlQueue, session, sessionId, monitor, target, observationWindowMode))
                {
                    session.ControlledShutdown();
                    EmitStatus(sessionId, "STOPPED", "explicit-stop", new { acceptedFrames });
                    return 0;
                }
                DrainEvidenceControls(evidenceQueue, evidenceLease, monitor, target, observationWindowMode);
                evidenceLease.Tick();
                var beforeCapture = monitor.Snapshot();
                if (!IsObservationTargetUsable(beforeCapture, observationWindowMode)
                    || !BackgroundObservationPolicy.IsSameObservationTarget(beforeCapture, target))
                {
                    evidenceLease.SignalStop();
                    EmitStatus(sessionId, "PAUSED", PauseReason(beforeCapture, observationWindowMode), TargetEvidence(beforeCapture));
                    session.ControlledShutdown();
                    return 3;
                }
                if (observationWindowMode == BackgroundObservationPolicy.BackgroundReadOnly
                    && !capture.IsClientAreaMappingCurrent())
                {
                    evidenceLease.SignalStop();
                    EmitStatus(sessionId, "PAUSED", "client-area-mapping-changed", TargetEvidence(beforeCapture));
                    session.ControlledShutdown();
                    return 3;
                }

                CapturedBgraFrame frame;
                var sourceRequestGate = evidenceLease.PendingRequestGateNs;
                try
                {
                    // Only an explicit SOURCE request selects after its own gate. Ordinary FRAME cadence is unchanged.
                    frame = sourceRequestGate is long requestGate
                        ? capture.CaptureAfterRequest(frameWaitMs, requestGate,
                            evidenceLease.PendingRequestDeadlineNs, () => !evidenceLease.IsOpen)
                        : capture.Capture(frameWaitMs);
                }
                catch (OperationCanceledException) when (sourceRequestGate is not null && !evidenceLease.IsOpen)
                {
                    // Closing warehouse intake does not terminate ordinary observation.
                    // A native_stop is processed at the beginning of the next iteration.
                    continue;
                }
                catch (TimeoutException) when (sourceRequestGate is not null)
                {
                    evidenceLease.Close("SOURCE_REQUEST_TIMEOUT");
                    continue;
                }
                catch (Exception ex)
                {
                    evidenceLease.SignalStop();
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
                if (!IsObservationTargetUsable(afterCapture, observationWindowMode)
                    || !BackgroundObservationPolicy.IsSameObservationTarget(afterCapture, target))
                {
                    evidenceLease.SignalStop();
                    EmitStatus(sessionId, "PAUSED", PauseReason(afterCapture, observationWindowMode), TargetEvidence(afterCapture));
                    session.ControlledShutdown();
                    return 3;
                }
                var sourceReadbackRejection = BackgroundObservationPolicy.BackgroundReadbackRejection(
                    observationWindowMode, frame.SourceTimestampNs, frame.CaptureTimestampNs, lastSourceTimestampNs);
                if (sourceReadbackRejection is not null
                    || (observationWindowMode == BackgroundObservationPolicy.BackgroundReadOnly
                        && !capture.IsClientAreaMappingCurrent()))
                {
                    evidenceLease.SignalStop();
                    EmitStatus(sessionId, "PAUSED", sourceReadbackRejection ?? "client-area-mapping-changed", new
                    {
                        sourceTimestampNs = frame.SourceTimestampNs, readbackTimestampNs = frame.CaptureTimestampNs,
                        lastSourceTimestampNs, target = TargetEvidence(afterCapture),
                    });
                    session.ControlledShutdown();
                    return 3;
                }
                lastSourceTimestampNs = frame.SourceTimestampNs;

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
                    evidenceLease.SignalStop();
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
                    evidenceLease.SignalStop();
                    EmitStatus(sessionId, "ERROR", "perception-not-received", transfer);
                    session.ControlledShutdown();
                    return 6;
                }

                var afterEngine = monitor.Snapshot();
                if (!IsObservationTargetUsable(afterEngine, observationWindowMode)
                    || !BackgroundObservationPolicy.IsSameObservationTarget(afterEngine, target))
                {
                    // A result that completed after a target boundary is not
                    // allowed to become the next observation's HUD state.
                    evidenceLease.SignalStop();
                    EmitStatus(sessionId, "PAUSED", PauseReason(afterEngine, observationWindowMode), TargetEvidence(afterEngine));
                    session.ControlledShutdown();
                    return 3;
                }
                var mappingAfterEngineCurrent = observationWindowMode != BackgroundObservationPolicy.BackgroundReadOnly
                    || capture.IsClientAreaMappingCurrent();
                var sourcePublicationRejection = BackgroundObservationPolicy.BackgroundPublicationRejection(
                    observationWindowMode, frame.SourceTimestampNs, ProtocolClock.NowNs());
                if (sourcePublicationRejection is not null || !mappingAfterEngineCurrent)
                {
                    evidenceLease.SignalStop();
                    EmitStatus(sessionId, "PAUSED", sourcePublicationRejection ?? "client-area-mapping-changed", new
                    {
                        sourceTimestampNs = frame.SourceTimestampNs, readbackTimestampNs = frame.CaptureTimestampNs,
                        target = TargetEvidence(afterEngine),
                    });
                    session.ControlledShutdown();
                    return 3;
                }

                var state = ReadJsonObject(Path.Combine(workDir, "engine_state.json"));
                var perception = transfer.TryGetValue("perceptionPayload", out var payload)
                    ? payload as JsonObject
                    : null;
                var scene = (string?)perception?["scene"] ?? "UNKNOWN";
                if (scene == "UNKNOWN")
                    unknownSinceMs ??= Environment.TickCount64;
                else
                    unknownSinceMs = null;
                var unknownExpired = unknownSinceMs.HasValue
                    && Environment.TickCount64 - unknownSinceMs.Value >= 10000;
                if (scene == "SETTLEMENT")
                {
                    settlementSinceMs ??= Environment.TickCount64;
                    settlementSourceDeadlineNs ??= checked(ProtocolClock.NowNs() + 70_000_000_000L);
                    settlementMatchId ??= (string?)state?["currentMatch"]?["id"];
                }
                var settlementReady = (bool?)state?["pipelineContext"]?["settlementReady"] == true;
                // Revoke advice on the first settlement observation, while
                // allowing the existing reader to see the completed animation.
                // No input is sent and focus/target guards remain in force.
                var settlementFinished = settlementSinceMs.HasValue && (
                    settlementReady
                    || Environment.TickCount64 - settlementSinceMs.Value >= 45000
                    || scene is "AUCTION_LOBBY" or "AUCTION_LOADING" or "CITY_TYCOON_HUB"
                        or "CITY_LEISURE_MENU" or "OPEN_WORLD" or "IN_AUCTION");
                var justClosedSettlement = settlementFinished && !settlementCollectionClosed;
                if (justClosedSettlement)
                    settlementCollectionClosed = true;
                var frameSequence = Convert.ToInt64(transfer.GetValueOrDefault("sequence") ?? 0);
                // Separate, explicit source channel. The closed-bill business publication guard below is unchanged.
                var evidenceTarget = EvidenceTargetIdentity(afterEngine);
                var evidenceMap = $"{capture.CaptureItemWidth}x{capture.CaptureItemHeight}:"
                    + $"{capture.ClientOffsetX},{capture.ClientOffsetY}:{frame.Width}x{frame.Height}";

                evidenceLease.UpdateContext(new WarehouseSourceContext(
                    (string?)state?["currentMatch"]?["id"] ?? "", evidenceTarget, evidenceMap,
                    frame.Width, frame.Height, settlementCollectionClosed && scene == "SETTLEMENT",
                    IsObservationTargetUsable(afterEngine, observationWindowMode), settlementSourceDeadlineNs ?? ProtocolClock.NowNs()));
                DrainEvidenceControls(evidenceQueue, evidenceLease, monitor, target, observationWindowMode);
                evidenceLease.TryPublish(new WarehouseSourceFrame(frame.Width, frame.Height, frame.Stride,
                    frame.Pixels, frame.SourceTimestampNs, frame.CaptureTimestampNs, frame.CapturedAtUtc,
                    frameSequence, (string?)state?["lastFrame"]?["pixelSha256"] ?? "",
                    (long?)state?["lastFrame"]?["frameSequence"] ?? -1L),
                    () => MatchesObservationTargetIdentity(evidenceTarget, monitor.Snapshot(), target, observationWindowMode)
                        && capture.IsClientAreaMappingCurrent());

                if (scene == "AUCTION_LOBBY" && !firstLobbyFrameWritten)
                {
                    // One bounded source sample; continue this same target and
                    // session through loading into the corresponding match.
                    if (firstFrameWritten)
                    {
                        var lobbyRawPath = Path.Combine(workDir, "lobby-frame.bmp");
                        var lobbyStatePath = Path.Combine(workDir, "lobby-frame-state.json");
                        WriteBmp(lobbyRawPath, frame.Width, frame.Height, frame.Pixels);
                        File.WriteAllText(lobbyStatePath,
                            JsonSerializer.Serialize(new
                            {
                                frameSequence,
                                frame.CaptureTimestampNs,
                                frame.CapturedAtUtc,
                                target = TargetEvidence(afterEngine),
                                state,
                                perception,
                            }, JsonLineOptions));
                    }
                    firstLobbyFrameWritten = true;
                }

                // Unknown revokes Main's lease through EmitObservation below,
                // but a brief transition must not destroy the capture session.
                // Focus/target/capture checks still fail closed on every frame.
                if (unknownExpired)
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
                    evidenceLease.SignalStop();
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

                if (settlementCollectionClosed && scene == "IN_AUCTION")
                {
                    var incomingMatchId = (string?)state?["currentMatch"]?["id"];
                    if (string.IsNullOrEmpty(settlementMatchId)
                        || string.IsNullOrEmpty(incomingMatchId)
                        || string.Equals(incomingMatchId, settlementMatchId, StringComparison.Ordinal))
                    {
                        // A scene label alone cannot resurrect the settled
                        // match. Wait for the worker-owned new-match boundary.
                        Thread.Sleep(Math.Max(intervalMs, 600));
                        continue;
                    }
                    settlementCollectionClosed = false;
                    settlementSinceMs = null;
                    settlementSourceDeadlineNs = null;
                    settlementMatchId = null;
                }
                if (settlementCollectionClosed && scene == "SETTLEMENT" && !justClosedSettlement)
                {
                    // Keep watching target/focus and the exit scene, without
                    // repeatedly publishing an already closed bill.
                    Thread.Sleep(Math.Max(intervalMs, 600));
                    continue;
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
                var latestRawPath = Path.Combine(workDir, scene == "SETTLEMENT"
                    ? (justClosedSettlement ? "settlement-final-frame.bmp" : "latest-settlement-frame.bmp")
                    : "latest-business-frame.bmp");
                var latestStatePath = Path.Combine(workDir, scene == "SETTLEMENT"
                    ? (justClosedSettlement ? "settlement-final-state.json" : "latest-settlement-state.json")
                    : "latest-business-state.json");
                WriteBmp(latestRawPath, frame.Width, frame.Height, frame.Pixels);
                File.WriteAllText(latestStatePath,
                    JsonSerializer.Serialize(new { frameSequence, frame.CaptureTimestampNs, state }, JsonLineOptions));

                if (observationWindowMode == BackgroundObservationPolicy.BackgroundReadOnly)
                {
                    var publicationTarget = monitor.Snapshot();
                    var publicationTargetUsable = IsObservationTargetUsable(publicationTarget, observationWindowMode)
                        && BackgroundObservationPolicy.IsSameObservationTarget(publicationTarget, target);
                    var publicationMappingCurrent = capture.IsClientAreaMappingCurrent();
                    var publicationReason = BackgroundObservationPolicy.BackgroundPublicationRejection(
                        observationWindowMode, frame.SourceTimestampNs, ProtocolClock.NowNs());
                    if (!publicationTargetUsable || !publicationMappingCurrent || publicationReason is not null)
                    {
                        evidenceLease.SignalStop();
                        EmitStatus(sessionId, "PAUSED", publicationReason ?? "publication-target-or-mapping-changed",
                            TargetEvidence(publicationTarget));
                        session.ControlledShutdown();
                        return 3;
                    }
                    afterEngine = publicationTarget;
                }
                var observationRejection = EmitObservation(
                    sessionId,
                    afterEngine,
                    frame,
                    transfer,
                state,
                acceptedFrames + 1,
                    latestRawPath,
                    capture,
                    observationWindowMode);
                if (observationRejection is not null)
                {
                    evidenceLease.SignalStop();
                    EmitStatus(sessionId, "PAUSED", observationRejection, new
                    {
                        sourceTimestampNs = frame.SourceTimestampNs,
                        readbackTimestampNs = frame.CaptureTimestampNs,
                    });
                    session.ControlledShutdown();
                    return 3;
                }
                acceptedFrames++;
                Thread.Sleep(settlementCollectionClosed ? Math.Max(intervalMs, 600) : intervalMs);
            }

            session.ControlledShutdown();
            EmitStatus(sessionId, "STOPPED", "frame-limit", new { acceptedFrames });
            return 0;
        }
        catch (Exception ex)
        {
            evidenceLease.SignalStop();
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

    private static string? EmitObservation(
        string sessionId,
        WindowMonitorSnapshot target,
        CapturedBgraFrame frame,
        IReadOnlyDictionary<string, object?> transfer,
        JsonObject? state,
        int acceptedFrames,
        string rawFramePath,
        WgcWindowCapture capture,
        string observationWindowMode)
    {
        var targetEvidence = JsonSerializer.SerializeToNode(TargetEvidence(target), JsonLineOptions);
        var publicationAtNs = ProtocolClock.NowNs();
        var sourceRejection = BackgroundObservationPolicy.BackgroundPublicationRejection(
            observationWindowMode, frame.SourceTimestampNs, publicationAtNs);
        if (sourceRejection is not null) return sourceRejection;
        var line = new JsonObject
        {
            ["type"] = "native_observation",
            ["schemaVersion"] = "native-observation-v1",
            ["status"] = "FRAME",
            ["observationSessionId"] = sessionId,
            ["observationWindowMode"] = observationWindowMode,
            ["sourceKind"] = "native_wgc",
            ["inputActions"] = false,
            ["formalHistoryWriter"] = false,
            ["acceptedFrameCount"] = acceptedFrames,
            ["target"] = targetEvidence,
            ["frame"] = new JsonObject
            {
                ["sequence"] = Convert.ToInt64(transfer.GetValueOrDefault("sequence") ?? 0),
                ["capturedAtNs"] = frame.CaptureTimestampNs,
                ["sourceTimestampNs"] = frame.SourceTimestampNs,
                ["capturedAtUtc"] = frame.CapturedAtUtc,
                ["width"] = frame.Width,
                ["height"] = frame.Height,
                ["stride"] = frame.Stride,
                ["captureItemWidth"] = capture.CaptureItemWidth,
                ["captureItemHeight"] = capture.CaptureItemHeight,
                ["clientOffsetX"] = capture.ClientOffsetX,
                ["clientOffsetY"] = capture.ClientOffsetY,
                ["freshnessMs"] = Math.Max(0.0, (publicationAtNs
                    - (observationWindowMode == BackgroundObservationPolicy.BackgroundReadOnly
                        ? frame.SourceTimestampNs : frame.CaptureTimestampNs)) / 1_000_000.0),
                ["rawFramePath"] = rawFramePath,
            },
            // The received envelope retains ownership of its payload node.
            ["perception"] = (transfer.GetValueOrDefault("perceptionPayload") as JsonObject)?.DeepClone(),
            ["currentMatch"] = state?["currentMatch"]?.DeepClone(),
            ["pipelineContext"] = state?["pipelineContext"]?.DeepClone(),
            ["lastFrame"] = state?["lastFrame"]?.DeepClone(),
        };
        EmitLine(line);
        return null;
    }

    private static void StartControlReader(BlockingCollection<JsonObject> queue,
        BlockingCollection<JsonObject> evidenceQueue, WarehouseEvidenceLease evidenceLease)
    {
        var reader = new Thread(() =>
        {
            try
            {
                while (true)
                {
                    var raw = ReadBoundedControlLine(out var oversized);
                    if (raw is null)
                    {
                        evidenceLease.SignalStop();
                        return;
                    }
                    if (oversized || Encoding.UTF8.GetByteCount(raw) > ProtocolConstants.MaxMessageBytes)
                    {
                        evidenceLease.Reject(new JsonObject(), "SOURCE_CONTROL_LINE_TOO_LARGE");
                        continue;
                    }
                    JsonObject? message;
                    try { message = JsonNode.Parse(raw) as JsonObject; }
                    catch (System.Text.Json.JsonException) { continue; }
                    if (message is null) continue;
                    if ((string?)message["type"] == WarehouseEvidenceLease.ControlType)
                    {
                        if (Encoding.UTF8.GetByteCount(raw) > 16 * 1024)
                        {
                            evidenceLease.Reject(message, "SOURCE_MESSAGE_TOO_LARGE");
                            continue;
                        }
                        evidenceLease.SignalClose(message);
                        if (!evidenceQueue.TryAdd(message)) evidenceLease.Reject(message, "SOURCE_CONTROL_QUEUE_FULL");
                    }
                    else
                    {
                        // Revoke evidence immediately; ordinary business shutdown keeps its existing queue.
                        if ((string?)message["type"] == "native_stop") evidenceLease.SignalStop();
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
            finally
            {
                // EOF, reader failure and explicit stop cannot leave an evidence lease alive.
                evidenceLease.SignalStop();
            }
        })
        {
            IsBackground = true,
            Name = "native-observation-controls",
        };
        reader.Start();
    }

    private static string? ReadBoundedControlLine(out bool oversized)
    {
        oversized = false;
        var text = new StringBuilder();
        while (true)
        {
            var next = Console.In.Read();
            if (next < 0) return text.Length == 0 && !oversized ? null : text.ToString();
            if (next == '\n') return text.ToString().TrimEnd('\r');
            if (text.Length >= ProtocolConstants.MaxMessageBytes) { oversized = true; continue; }
            if (!oversized) text.Append((char)next);
        }
    }

    private static JsonObject EvidenceTargetIdentity(WindowMonitorSnapshot snapshot) => new()
    {
        ["targetHwnd"] = snapshot.TargetHwnd, ["targetPid"] = snapshot.TargetPid,
        ["generation"] = snapshot.Generation,
        ["processInstanceToken"] = snapshot.TargetIdentity?.ProcessInstanceToken,
    };

    private static void DrainEvidenceControls(BlockingCollection<JsonObject> queue,
        WarehouseEvidenceLease lease, WindowMonitor monitor, WindowMonitorSnapshot target,
        string observationWindowMode)
    {
        while (queue.TryTake(out var message))
        {
            // Input is separately bound to an explicitly authorized source lease.
            var op = (string?)message["operation"];
            if (op is "OPEN" or "REQUEST_PAGE" or "SCROLL_DOWN"
                && !MatchesObservationTargetIdentity(message["expectedTargetInstance"] as JsonObject,
                    monitor.Snapshot(), target, observationWindowMode))
                lease.Reject(message, "SOURCE_TARGET_UNUSABLE");
            else lease.Handle(message);
        }
    }

    private static bool DrainControls(
        BlockingCollection<JsonObject> queue,
        SupervisorSession session,
        string sessionId,
        WindowMonitor monitor,
        WindowMonitorSnapshot sessionTarget,
        string observationWindowMode)
    {
        void EmitStatus(string id, string status, string reason, object? details) =>
            NativeObservationService.EmitStatus(id, status, reason, details, observationWindowMode);
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
            if (!MatchesObservationTargetIdentity(expectedTarget, activeTarget, sessionTarget, observationWindowMode))
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

    private static bool MatchesObservationTargetIdentity(JsonObject? expected,
        WindowMonitorSnapshot active, WindowMonitorSnapshot sessionTarget, string observationWindowMode)
    {
        var window = ReadObservationWindowState(active.TargetHwnd);
        return BackgroundObservationPolicy.MatchesObservationTargetIdentity(observationWindowMode, expected,
            active, sessionTarget, window.Minimized, window.ClientAreaAvailable, window.Width, window.Height);
    }

    private static void EmitStatus(string sessionId, string status, string reason, object? details,
        string observationWindowMode = BackgroundObservationPolicy.Foreground)
    {
        var line = new JsonObject
        {
            ["type"] = "native_observation",
            ["schemaVersion"] = "native-observation-v1",
            ["status"] = status,
            ["observationSessionId"] = sessionId,
            ["observationWindowMode"] = observationWindowMode,
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

    private static WindowMonitorSnapshot WaitForTarget(WindowMonitor monitor, int timeoutMs, string observationWindowMode)
    {
        var deadline = Environment.TickCount64 + timeoutMs;
        var last = monitor.Snapshot();
        while (Environment.TickCount64 < deadline)
        {
            last = monitor.Snapshot();
            if (IsObservationTargetUsable(last, observationWindowMode))
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

    private static bool IsObservationTargetUsable(WindowMonitorSnapshot snapshot, string observationWindowMode)
    {
        var window = ReadObservationWindowState(snapshot.TargetHwnd);
        return BackgroundObservationPolicy.IsObservationTargetUsable(observationWindowMode, snapshot,
            window.Minimized, window.ClientAreaAvailable, window.Width, window.Height);
    }

    private static string PauseReason(WindowMonitorSnapshot snapshot, string observationWindowMode)
    {
        if (snapshot.TargetHwnd == 0 || !snapshot.IsTargetAlive)
        {
            return "target-lost";
        }
        if (observationWindowMode == BackgroundObservationPolicy.Foreground && !snapshot.IsTargetForeground)
        {
            return "focus-lost";
        }
        if (snapshot.TargetIdentity?.IsVisible != true) return "target-hidden";
        var window = ReadObservationWindowState(snapshot.TargetHwnd);
        if (window.Minimized) return "target-minimized";
        if (!window.ClientAreaAvailable || window.Width <= 0 || window.Height <= 0
            || window.Width > 1920 || window.Height > 1080) return "client-size-unavailable-or-invalid";
        return "target-identity-changed";
    }

    private static object TargetEvidence(WindowMonitorSnapshot snapshot)
    {
        var window = ReadObservationWindowState(snapshot.TargetHwnd);
        return new
        {
            targetHwnd = snapshot.TargetHwnd,
            targetPid = snapshot.TargetPid,
            foregroundHwnd = snapshot.ForegroundHwnd,
            isTargetAlive = snapshot.IsTargetAlive,
            isTargetForeground = snapshot.IsTargetForeground,
            isTargetVisible = snapshot.IsTargetAlive && snapshot.TargetIdentity?.IsVisible == true,
            isTargetMinimized = window.Minimized,
            clientAreaAvailable = window.ClientAreaAvailable,
            clientWidth = window.Width,
            clientHeight = window.Height,
            generation = snapshot.Generation,
            observedAtNs = snapshot.ObservedAtNs,
            reason = snapshot.Reason,
            identity = snapshot.TargetIdentity,
        };
    }

    private readonly record struct ObservationWindowState(bool Minimized, bool ClientAreaAvailable, int Width, int Height);

    private static ObservationWindowState ReadObservationWindowState(long hwnd)
    {
        if (hwnd == 0) return new ObservationWindowState(true, false, 0, 0);
        try
        {
            var handle = new IntPtr(hwnd);
            var minimized = IsIconic(handle);
            if (!GetClientRect(handle, out var client)) return new ObservationWindowState(minimized, false, 0, 0);
            return new ObservationWindowState(minimized, true,
                checked(client.Right - client.Left), checked(client.Bottom - client.Top));
        }
        catch (Exception) { return new ObservationWindowState(true, false, 0, 0); }
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct ClientRect { public int Left, Top, Right, Bottom; }

    [DllImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool IsIconic(IntPtr hwnd);

    [DllImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool GetClientRect(IntPtr hwnd, out ClientRect client);

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
