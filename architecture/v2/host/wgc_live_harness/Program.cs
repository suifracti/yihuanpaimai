using System;
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

internal static class Program
{
    private static readonly JsonSerializerOptions JsonOut = new()
    {
        WriteIndented = true,
        Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
    };

    public static int Main(string[] args)
    {
        // Main's redirected control/observation pipes are UTF-8, independent
        // of the Windows console code page (including CREATE_NO_WINDOW).
        Console.InputEncoding = new UTF8Encoding(false);
        Console.OutputEncoding = new UTF8Encoding(false);
        if (string.Equals(Arg(args, "--mode", "probe"), "live", StringComparison.OrdinalIgnoreCase))
        {
            return NativeObservationService.Run(args);
        }

        var outputPath = Path.GetFullPath(Arg(
            args,
            "--output",
            Path.Combine("build", "goal-luna", "native-bridge", "real-window-v2-3", "wgc-mmf-result.json")));

        try
        {
            var (evidence, ok) = RunCore(args, outputPath);
            WriteJson(outputPath, evidence);
            Console.WriteLine(JsonSerializer.Serialize(evidence, JsonOut));
            return ok ? 0 : 1;
        }
        catch (Exception ex)
        {
            var evidence = new
            {
                schemaVersion = "v2.3.wgc-mmf-real-window.v1",
                ok = false,
                productionReachable = false,
                realInputPathReachable = false,
                realInputExecuted = false,
                earliestBlocker = $"{ex.GetType().Name}: {ex.Message}",
                exceptionType = ex.GetType().FullName,
            };
            WriteJson(outputPath, evidence);
            Console.WriteLine(JsonSerializer.Serialize(evidence, JsonOut));
            return 1;
        }
    }

    private static (object Evidence, bool Ok) RunCore(string[] args, string outputPath)
    {
        var repoRoot = FindRepoRoot(Arg(args, "--repo", Directory.GetCurrentDirectory()));
        var specImage = Arg(args, "--spec-image", "htgame.exe");
        var specClass = Arg(args, "--spec-class", "UnrealWindow");
        var pythonExe = Arg(args, "--python", "python");
        var targetWaitMs = int.Parse(Arg(args, "--target-wait-ms", "15000"));
        var frameCount = int.Parse(Arg(args, "--frame-count", "5"));
        var frameWaitMs = int.Parse(Arg(args, "--frame-wait-ms", "5000"));
        var workDir = Path.GetFullPath(Arg(
            args,
            "--work-dir",
            Path.Combine(repoRoot, "build", "goal-luna", "native-bridge", "real-window-v2-3")));
        var capturePath = Path.GetFullPath(Arg(
            args,
            "--capture",
            Path.Combine(workDir, "real-game-frame.bmp")));
        Directory.CreateDirectory(workDir);

        using var monitor = new WindowMonitor(new WindowMonitorOptions
        {
            Spec = new TargetWindowSpec(specImage, specClass),
            RequireVisible = true,
            SkipOwnProcessInHook = true,
            EventQueueCapacity = 4096,
        });
        monitor.Start();

        var target = WaitForTarget(monitor, targetWaitMs);
        if (target.TargetIdentity is null || target.TargetHwnd == 0 || !target.IsTargetAlive)
        {
            var blocker = new
            {
                schemaVersion = "v2.3.wgc-mmf-real-window.v1",
                ok = false,
                productionReachable = false,
                realInputPathReachable = false,
                realInputExecuted = false,
                target = TargetEvidence(target),
                earliestBlocker = "real-target-window-not-found-or-not-alive",
                note = "No WGC or MMF work was attempted after target discovery failed.",
            };
            return (blocker, false);
        }

        using var capture = new WgcWindowCapture(new IntPtr(target.TargetHwnd));
        var sessionId = $"wgc-v23-{Guid.NewGuid():N}";
        var tracePath = Path.Combine(workDir, "host-trace.jsonl");
        var engineLogPath = Path.Combine(workDir, "engine.log.jsonl");
        var engineScript = Path.Combine(repoRoot, "architecture", "v2", "host", "engine_frame_probe", "engine_frame_probe.py");
        var contractsDir = Path.Combine(repoRoot, "architecture", "v2", "contracts");
        var hostFrames = new List<Dictionary<string, object?>>();
        var captureErrors = new List<string>();
        var publishedCount = 0;
        var droppedCount = 0;
        var captureFailureCount = 0;
        Dictionary<string, object?>? shutdown = null;
        FrameRingStats? ringStats = null;

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
            AcceptTimeoutMs = 15000,
            EnableFrameTransport = true,
        });

        session.StartGeneration(coldBoot: true);
        var handshake = session.Handshake(coldBoot: true);
        session.ReachReady(coldBoot: true, noRecoverableBusinessState: true);

        for (var i = 0; i < frameCount; i++)
        {
            CapturedBgraFrame frame;
            try
            {
                frame = capture.Capture(frameWaitMs);
            }
            catch (Exception ex)
            {
                captureFailureCount++;
                captureErrors.Add($"frame-{i + 1}: {ex.GetType().Name}: {ex.Message}");
                break;
            }

            if (i == 0)
            {
                WriteBmp(capturePath, frame.Width, frame.Height, frame.Pixels);
            }

            var hostSha = Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(frame.Pixels)).ToLowerInvariant();
            var transfer = session.SendFrame(
                frame.Pixels,
                frame.Width,
                frame.Height,
                frame.Stride,
                frame.CaptureTimestampNs,
                timeoutMs: 5000);
            transfer["captureIndex"] = i + 1;
            transfer["hostPixelSha256"] = hostSha;
            transfer["capturedWidth"] = frame.Width;
            transfer["capturedHeight"] = frame.Height;
            transfer["capturedStride"] = frame.Stride;
            transfer["capturedBufferLength"] = frame.Pixels.Length;
            hostFrames.Add(transfer);

            if (transfer.TryGetValue("published", out var published) && published is true)
            {
                publishedCount++;
            }
            else if (transfer.TryGetValue("bufferUnavailable", out var unavailable) && unavailable is true)
            {
                droppedCount++;
            }
        }

        ringStats = session.FrameRing?.SnapshotStats();
        shutdown = session.ControlledShutdown();
        var engineEvidence = ReadJsonObject(Path.Combine(workDir, "engine_frame_probe.json"));
        var engineRows = ReadEngineRows(engineEvidence);
        var sequenceList = hostFrames
            .Where(row => row.TryGetValue("sequence", out _))
            .Select(row => Convert.ToInt64(row["sequence"]!))
            .ToArray();
        var sequencesMonotonic = sequenceList.Zip(sequenceList.Skip(1), (a, b) => b > a).All(x => x);
        var engineChecks = MatchEngineRows(hostFrames, engineRows);
        var slotsFree = ringStats is not null
            && ringStats.Slots.All(slot => slot.State == FrameRingSlotState.Free);
        var acknowledgementsAccepted = hostFrames.Count > 0
            && hostFrames.All(row => row.TryGetValue("ackAccepted", out var value) && value is true);
        var perceptionResponsesReceived = hostFrames.Count > 0
            && hostFrames.All(row => row.TryGetValue("perceptionReceived", out var value) && value is true);
        var contentValid = hostFrames.Count > 0
            && publishedCount == hostFrames.Count
            && engineChecks.All(row => row.ContentValid && row.MetadataMatch && row.ChecksumMatch && row.HostShaMatches);
        var ok = target.TargetHwnd != 0
            && capture.Width > 0
            && capture.Height > 0
            && hostFrames.Count == frameCount
            && publishedCount == frameCount
            && droppedCount == 0
            && sequencesMonotonic
            && acknowledgementsAccepted
            && perceptionResponsesReceived
            && contentValid
            && slotsFree;

        var evidence = new
        {
            schemaVersion = "v2.3.wgc-mmf-real-window.v1",
            ok,
            productionReachable = target.TargetHwnd != 0 && capture.Width > 0 && capture.Height > 0,
            realInputPathReachable = false,
            realInputExecuted = false,
            branch = GetGitValue(repoRoot, "branch --show-current"),
            head = GetGitValue(repoRoot, "rev-parse HEAD"),
            worktree = repoRoot,
            target = TargetEvidence(target),
            wgc = new
            {
                captureCreated = true,
                width = capture.Width,
                height = capture.Height,
                pixelFormat = "BGRA8",
                directTargetHwnd = target.TargetHwnd,
            },
            capturedFrames = hostFrames.Count,
            publishedFrames = publishedCount,
            droppedFrames = droppedCount,
            droppedDefinition = "successful WGC captures rejected only because all four fixed-v1 MMF slots were still locked; capture/readback failures are reported separately",
            captureFailures = captureFailureCount,
            captureErrors,
            representativeCapturePath = File.Exists(capturePath) ? capturePath : null,
            frameTransfers = hostFrames,
            frameChecks = engineChecks,
            frameGeometry = hostFrames.Count == 0 ? null : new
            {
                width = hostFrames[0].GetValueOrDefault("capturedWidth"),
                height = hostFrames[0].GetValueOrDefault("capturedHeight"),
                stride = hostFrames[0].GetValueOrDefault("capturedStride"),
                bufferLength = hostFrames[0].GetValueOrDefault("capturedBufferLength"),
                format = ProtocolConstants.DefaultPixelFormatBgra8,
            },
            frameHeaderReadyMetadataMatch = engineChecks.Count > 0 && engineChecks.All(row => row.MetadataMatch),
            sequenceMonotonic = sequencesMonotonic,
            engineReadMmfFrame = engineChecks.Count > 0 && engineChecks.All(row => row.ContentValid),
            checksumAndContentValid = contentValid,
            frameAckReleasedSlot = acknowledgementsAccepted && slotsFree,
            sequenceList,
            ringStats,
            slotsFreeAfterAck = slotsFree,
            engineEvidence,
            handshake = new
            {
                status = handshake.HelloAckStatus,
                readiness = handshake.EngineReadiness,
                businessReady = handshake.EngineBusinessReady,
            },
            shutdown,
            earliestBlocker = ok ? "NONE" : FindEarliestBlocker(
                target,
                captureFailureCount,
                hostFrames,
                frameCount,
                publishedCount,
                droppedCount,
                engineChecks,
                sequencesMonotonic,
                acknowledgementsAccepted,
                perceptionResponsesReceived,
                slotsFree),
            unverified = new[]
            {
                "真实输入执行（本轮明确禁用）",
                "游戏重启或 HWND 销毁/重建",
                "OCR、识图、solver、history、V2-4 CoreWebView2、Overlay",
            },
        };
        return (evidence, ok);
    }

    private static WindowMonitorSnapshot WaitForTarget(WindowMonitor monitor, int timeoutMs)
    {
        var deadline = Environment.TickCount64 + timeoutMs;
        WindowMonitorSnapshot last = monitor.Snapshot();
        while (Environment.TickCount64 < deadline)
        {
            last = monitor.Snapshot();
            if (last.TargetHwnd != 0 && last.IsTargetAlive && last.TargetIdentity is { IsPresent: true })
            {
                return last;
            }
            Thread.Sleep(50);
        }
        return last;
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

    private sealed record EngineFrameCheck(
        long Sequence,
        bool ContentValid,
        bool MetadataMatch,
        bool ChecksumMatch,
        bool HostShaMatches,
        string? EngineSha256,
        string? HostSha256,
        string? Error);

    private static List<JsonObject> ReadEngineRows(JsonObject? evidence)
    {
        var rows = new List<JsonObject>();
        if (evidence?["frames"] is not JsonArray array)
        {
            return rows;
        }
        foreach (var node in array)
        {
            if (node is JsonObject row)
            {
                rows.Add(row);
            }
        }
        return rows;
    }

    private static List<EngineFrameCheck> MatchEngineRows(
        IReadOnlyList<Dictionary<string, object?>> hostFrames,
        IReadOnlyList<JsonObject> engineRows)
    {
        var checks = new List<EngineFrameCheck>();
        foreach (var host in hostFrames)
        {
            var sequence = host.TryGetValue("sequence", out var sequenceValue)
                ? Convert.ToInt64(sequenceValue)
                : -1;
            var row = engineRows.FirstOrDefault(candidate =>
                candidate["frameReadyPayload"]?["sequence"]?.GetValue<long>() == sequence);
            var engineSha = row?["pixelSha256"]?.GetValue<string>();
            var hostSha = host.TryGetValue("hostPixelSha256", out var hostValue)
                ? hostValue as string
                : null;
            checks.Add(new EngineFrameCheck(
                sequence,
                row?["contentValid"]?.GetValue<bool>() == true,
                row?["metadataMatch"]?.GetValue<bool>() == true,
                row?["checksumMatch"]?.GetValue<bool>() == true,
                !string.IsNullOrEmpty(engineSha) && string.Equals(engineSha, hostSha, StringComparison.OrdinalIgnoreCase),
                engineSha,
                hostSha,
                row?["error"]?.GetValue<string>()));
        }
        return checks;
    }

    private static string FindEarliestBlocker(
        WindowMonitorSnapshot target,
        int captureFailures,
        IReadOnlyList<Dictionary<string, object?>> hostFrames,
        int expectedFrames,
        int published,
        int dropped,
        IReadOnlyList<EngineFrameCheck> engineChecks,
        bool sequencesMonotonic,
        bool acks,
        bool perception,
        bool slotsFree)
    {
        if (target.TargetHwnd == 0 || !target.IsTargetAlive)
        {
            return "real-target-window-not-found-or-not-alive";
        }
        if (captureFailures > 0 || hostFrames.Count < expectedFrames)
        {
            return "wgc-frame-capture-or-readback-failed";
        }
        if (published < hostFrames.Count && dropped > 0)
        {
            return "mmf-fixed-ring-buffer-unavailable-before-publication";
        }
        if (!acks)
        {
            return "engine-frame-ack-not-accepted";
        }
        if (!perception)
        {
            return "engine-transport-response-not-received";
        }
        if (engineChecks.Count != hostFrames.Count || engineChecks.Any(row => !row.ContentValid))
        {
            return "engine-readonly-mmf-content-validation-failed";
        }
        if (engineChecks.Any(row => !row.MetadataMatch))
        {
            return "frameheader-frame-ready-metadata-mismatch";
        }
        if (engineChecks.Any(row => !row.ChecksumMatch || !row.HostShaMatches))
        {
            return "frame-payload-integrity-check-failed";
        }
        if (!sequencesMonotonic)
        {
            return "frame-sequence-not-monotonic";
        }
        if (!slotsFree)
        {
            return "ack-did-not-release-all-slots";
        }
        return "unknown-v2-3-transport-failure";
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

    private static string GetGitValue(string repoRoot, string arguments)
    {
        using var process = new System.Diagnostics.Process
        {
            StartInfo = new System.Diagnostics.ProcessStartInfo
            {
                FileName = "git",
                Arguments = arguments,
                WorkingDirectory = repoRoot,
                UseShellExecute = false,
                RedirectStandardOutput = true,
                RedirectStandardError = true,
                CreateNoWindow = true,
            },
        };
        process.Start();
        var value = process.StandardOutput.ReadToEnd().Trim();
        process.WaitForExit(5000);
        return value;
    }

    private static JsonObject? ReadJsonObject(string path)
    {
        if (!File.Exists(path))
        {
            return null;
        }
        return JsonNode.Parse(File.ReadAllText(path)) as JsonObject;
    }

    private static void WriteJson(string path, object value)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(path))!);
        File.WriteAllText(path, JsonSerializer.Serialize(value, JsonOut), new UTF8Encoding(false));
    }

    private static void WriteBmp(string path, int width, int height, byte[] bgra)
    {
        var stride = checked(width * 4);
        if (bgra.Length != checked(stride * height))
        {
            throw new InvalidOperationException("representative BMP payload length does not match frame geometry");
        }

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
}
