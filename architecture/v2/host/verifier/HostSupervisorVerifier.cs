using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using NteHost.Protocol;

namespace NteHost.Verifier;

/// <summary>
/// V2-1 .NET verifier (D01-D10).
///
/// Deliberately independent of architecture/v2/verifier/ContractVerifier.csproj,
/// which is the frozen V2-0 artifact (40/40). V2-1 does not modify it; instead this
/// project re-derives every host-side constant from the same catalog so that the
/// C# host cannot silently drift away from the single schema truth.
/// </summary>
internal static class Program
{
    private sealed record TestResult(string Name, bool Passed, string Detail);

    private static readonly List<TestResult> Results = new();
    private static string _contractsDir = string.Empty;
    private static MessageCatalog _catalog = null!;

    private static int Main(string[] args)
    {
        var options = ParseArgs(args);
        var outPath = options.GetValueOrDefault("--out", string.Empty);
        var metricsPath = options.GetValueOrDefault("--metrics", string.Empty);
        var startDir = options.GetValueOrDefault("--start-dir", AppContext.BaseDirectory);

        try
        {
            _contractsDir = MessageCatalog.ResolveContractsDirectory(options.GetValueOrDefault("--contracts", null), startDir);
            _catalog = MessageCatalog.LoadFromFile(Path.Combine(_contractsDir, "message_catalog_v1.json"));
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"FATAL: cannot load the message catalog: {ex.Message}");
            return 2;
        }

        Run("D01_HostProtocol_Envelope_MatchesCatalog", D01);
        Run("D02_HostProtocol_FrameHeader_Is64Bytes", D02);
        Run("D03_HostProtocol_ErrorCodes_MatchCatalog", D03);
        Run("D04_HostProtocol_Geometry_MatchesCatalog", D04);
        Run("D05_Lifecycle_TransitionTable_MatchesModels", D05);
        Run("D06_SequenceTracker_GenerationReset_AcceptsZero", D06);
        Run("D07_SequenceTracker_StaleGeneration_Rejected", D07);
        Run("D08_Framing_RejectsOversizeAndIncomplete", D08);
        Run("D09_Supervisor_Metrics_SeparatelyReported", () => D09(metricsPath));
        Run("D10_Supervisor_NoBusinessReadyImpersonation", () => D10(metricsPath));

        var passed = Results.Count(r => r.Passed);
        var failed = Results.Count(r => !r.Passed);
        var payload = new
        {
            schemaVersion = "v2.1.host.supervisor.verifier.v1",
            phase = "V2-1",
            protocolVersion = ProtocolConstants.ProtocolVersion,
            contractsDirectory = _contractsDir,
            metricsArtifact = string.IsNullOrEmpty(metricsPath) ? null : metricsPath,
            totalTests = Results.Count,
            passedTests = passed,
            failedTests = failed,
            allPassed = failed == 0,
            results = Results,
        };

        var json = JsonSerializer.Serialize(payload, new JsonSerializerOptions { WriteIndented = true });
        if (!string.IsNullOrEmpty(outPath))
        {
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outPath))!);
            File.WriteAllText(outPath, json + Environment.NewLine, new UTF8Encoding(false));
        }
        Console.WriteLine(json);
        Console.WriteLine();
        Console.WriteLine($"Summary: {passed}/{Results.Count} tests passed (allPassed={failed == 0})");
        return failed == 0 ? 0 : 1;
    }

    private static void Run(string name, Func<string> body)
    {
        try
        {
            var detail = body();
            Results.Add(new TestResult(name, true, detail));
            Console.Error.WriteLine($"PASS {name}: {detail}");
        }
        catch (Exception ex)
        {
            Results.Add(new TestResult(name, false, $"{ex.GetType().Name}: {ex.Message}"));
            Console.Error.WriteLine($"FAIL {name}: {ex.GetType().Name}: {ex.Message}");
        }
    }

    // ------------------------------------------------------------------ D01..D10

    private static string D01()
    {
        var envelopeSchema = _catalog.EnvelopeSchema;
        var required = ((JsonArray)envelopeSchema["requiredFields"]!).Select(n => (string)n!).ToList();
        string[] expected =
        {
            "protocolVersion", "sessionId", "messageType", "requestId",
            "correlationId", "sequence", "monotonicTimestampNs", "payload",
        };
        Require(required.SequenceEqual(expected),
            $"catalog envelope requiredFields [{string.Join(", ", required)}] != host envelope [{string.Join(", ", expected)}]");

        var properties = (JsonObject)envelopeSchema["properties"]!;
        Require(properties.Count == expected.Length, $"catalog declares {properties.Count} envelope properties, host has {expected.Length}");

        var declared = properties.Select(kv => kv.Key).ToHashSet(StringComparer.Ordinal);
        foreach (var field in expected)
        {
            Require(declared.Contains(field), $"catalog envelope is missing '{field}'");
        }

        // messageType enum must equal the 14 host message types.
        var messageTypeEnum = ((JsonArray)properties["messageType"]!["enum"]!).Select(n => (string)n!).OrderBy(n => n, StringComparer.Ordinal).ToList();
        var hostTypes = MessageTypes.All.OrderBy(n => n, StringComparer.Ordinal).ToList();
        Require(messageTypeEnum.SequenceEqual(hostTypes),
            $"catalog messageType enum [{string.Join(", ", messageTypeEnum)}] != host MessageTypes [{string.Join(", ", hostTypes)}]");

        // The host parser must accept a minimal valid envelope on the real wire path
        // (UTF-8 JSON text) and reject a missing field.
        const string validJson =
            "{\"protocolVersion\":\"1.0.0\",\"sessionId\":\"s\",\"messageType\":\"HEARTBEAT\"," +
            "\"requestId\":\"r\",\"correlationId\":null,\"sequence\":0,\"monotonicTimestampNs\":0,\"payload\":{}}";
        Envelope.Parse(System.Text.Encoding.UTF8.GetBytes(validJson));

        // A non-integral sequence must not be coerced into an integer.
        const string fractionalJson =
            "{\"protocolVersion\":\"1.0.0\",\"sessionId\":\"s\",\"messageType\":\"HEARTBEAT\"," +
            "\"requestId\":\"r\",\"correlationId\":null,\"sequence\":1.5,\"monotonicTimestampNs\":0,\"payload\":{}}";
        var fractionalRejected = false;
        try
        {
            Envelope.Parse(System.Text.Encoding.UTF8.GetBytes(fractionalJson));
        }
        catch (ProtocolViolationException ex)
        {
            fractionalRejected = ex.ErrorCode == ErrorCodes.MalformedEnvelope;
        }
        Require(fractionalRejected, "a fractional sequence was coerced instead of rejected");

        var invalid = (JsonObject)JsonNode.Parse(validJson)!;
        invalid.Remove("requestId");
        var rejected = false;
        try
        {
            Envelope.Parse(invalid);
        }
        catch (ProtocolViolationException ex)
        {
            rejected = ex.ErrorCode == ErrorCodes.MalformedEnvelope;
        }
        Require(rejected, "envelope missing requestId was not rejected with ERR_MALFORMED_ENVELOPE");

        return "8 envelope fields match the catalog; 14 message types match; no-coercion and missing-field rejection verified";
    }

    private static string D02()
    {
        var header = new FrameHeaderV1
        {
            Sequence = 101,
            Width = 1920,
            Height = 1080,
            Stride = 7680,
            PixelFormat = 1,
            BufferLength = 8294400,
            Flags = 1,
            CaptureTimestampNs = 1000000000,
            ProducerTimestampNs = 1003200000,
            CornerChecksum = 0x12345678,
            Reserved = 0,
        };
        var packed = header.Pack();
        Require(packed.Length == 64, $"packed header is {packed.Length} bytes, expected 64");

        var offsets = new (string Name, int Offset, int Size)[]
        {
            ("magic", FrameHeaderV1.OffsetMagic, 4),
            ("headerVersion", FrameHeaderV1.OffsetHeaderVersion, 4),
            ("sequence", FrameHeaderV1.OffsetSequence, 8),
            ("width", FrameHeaderV1.OffsetWidth, 4),
            ("height", FrameHeaderV1.OffsetHeight, 4),
            ("stride", FrameHeaderV1.OffsetStride, 4),
            ("pixelFormat", FrameHeaderV1.OffsetPixelFormat, 4),
            ("bufferLength", FrameHeaderV1.OffsetBufferLength, 4),
            ("flags", FrameHeaderV1.OffsetFlags, 4),
            ("captureTimestampNs", FrameHeaderV1.OffsetCaptureTimestampNs, 8),
            ("producerTimestampNs", FrameHeaderV1.OffsetProducerTimestampNs, 8),
            ("cornerChecksum", FrameHeaderV1.OffsetCornerChecksum, 4),
            ("reserved", FrameHeaderV1.OffsetReserved, 4),
        };

        var layout = JsonNode.Parse(File.ReadAllText(Path.Combine(_contractsDir, "frame_buffer_layout_v1.json")))!;
        var fields = (JsonArray)layout["headerStructure"]!["fields"]!;
        Require(fields.Count == offsets.Length, $"catalog declares {fields.Count} header fields, host has {offsets.Length}");

        foreach (var (name, offset, size) in offsets)
        {
            var match = fields.FirstOrDefault(f => (string?)f!["name"] == name)
                        ?? throw new InvalidOperationException($"catalog header is missing field '{name}'");
            Require((int?)match["offset"] == offset, $"'{name}' offset: host={offset}, catalog={match["offset"]}");
            Require((int?)match["size"] == size, $"'{name}' size: host={size}, catalog={match["size"]}");
        }

        var golden = JsonNode.Parse(File.ReadAllText(Path.Combine(_contractsDir, "golden_vectors_v1.json")))!;
        var headerVector = (JsonObject)golden["frameHeaderVector"]!;
        var expectedHex = (string)headerVector["packedHex"]!;
        var actualHex = Convert.ToHexString(packed).ToLowerInvariant();
        Require(actualHex == expectedHex, $"packed header hex mismatch: host={actualHex}, golden={expectedHex}");

        var roundTrip = FrameHeaderV1.Unpack(packed);
        Require(roundTrip.CornerChecksum == header.CornerChecksum && roundTrip.Sequence == header.Sequence,
            "frame header round-trip mismatch");

        return $"64-byte layout, 13 field offsets and golden packedHex all match";
    }

    private static string D03()
    {
        // Compare against error_catalog_v1.json, which is the full error authority
        // (37 codes). message_catalog_v1.json -> failClosedErrorCodes is only the
        // subset of codes that are fail-closed at the message layer.
        var errorCatalog = JsonNode.Parse(File.ReadAllText(Path.Combine(_contractsDir, "error_catalog_v1.json")))!;
        var catalogCodes = ((JsonArray)errorCatalog["errors"]!)
            .Select(e => (string)e!["errorCode"]!)
            .OrderBy(c => c, StringComparer.Ordinal)
            .ToList();
        var hostCodes = ErrorCodes.All.OrderBy(c => c, StringComparer.Ordinal).ToList();

        var missingInHost = catalogCodes.Except(hostCodes).ToList();
        var extraInHost = hostCodes.Except(catalogCodes).ToList();
        Require(missingInHost.Count == 0, $"host is missing catalog error codes: [{string.Join(", ", missingInHost)}]");
        Require(extraInHost.Count == 0, $"host declares error codes absent from the catalog: [{string.Join(", ", extraInHost)}]");
        Require(catalogCodes.Distinct().Count() == catalogCodes.Count, "catalog error codes contain duplicates");

        // The codes V2-1 actually raises must be catalog codes.
        foreach (var code in new[]
                 {
                     ErrorCodes.HandshakeTimeout, ErrorCodes.StaleGeneration, ErrorCodes.StaleSession,
                     ErrorCodes.StaleSequence, ErrorCodes.RingGeometryMismatch, ErrorCodes.InvalidStateTransition,
                     ErrorCodes.MessageTooLarge, ErrorCodes.IncompleteFrame, ErrorCodes.StreamEof,
                     ErrorCodes.PipeDisconnected, ErrorCodes.BufferUnavailable, ErrorCodes.SchemaValidationFailed,
                 })
        {
            Require(catalogCodes.Contains(code), $"V2-1 raises '{code}' which is not in the catalog");
        }

        // Every fail-closed code named by the message catalog must also exist here.
        var failClosed = _catalog.FailClosedErrorCodes;
        var dangling = failClosed.Except(catalogCodes).ToList();
        Require(dangling.Count == 0, $"message catalog names fail-closed codes absent from the error catalog: [{string.Join(", ", dangling)}]");

        return $"{catalogCodes.Count} error-catalog codes match the host set exactly; all {failClosed.Count} message-catalog fail-closed codes resolve";
    }

    private static string D04()
    {
        var geometry = _catalog.RingBufferGeometry;
        var expected = new (string Key, int Value)[]
        {
            ("slotCount", ProtocolConstants.SlotCount),
            ("maxWidth", ProtocolConstants.MaxFrameWidth),
            ("maxHeight", ProtocolConstants.MaxFrameHeight),
            ("slotPayloadCapacityBytes", ProtocolConstants.SlotPayloadCapacityBytes),
            ("headerSizeBytes", ProtocolConstants.FrameHeaderSize),
            ("slotSizeBytes", ProtocolConstants.SlotSizeBytes),
            ("slotAlignmentBytes", ProtocolConstants.SlotAlignmentBytes),
            ("mapTotalSizeBytes", ProtocolConstants.MapTotalSizeBytes),
        };
        foreach (var (key, value) in expected)
        {
            Require((int?)geometry[key] == value, $"geometry '{key}': host={value}, catalog={geometry[key]}");
        }

        Require((string?)geometry["policy"] == ProtocolConstants.RingGeometryPolicy,
            $"geometry policy: host={ProtocolConstants.RingGeometryPolicy}, catalog={geometry["policy"]}");
        Require((bool?)geometry["geometryIsNegotiated"] == false, "catalog geometryIsNegotiated is not false");

        // Derived invariants must hold.
        Require(ProtocolConstants.SlotSizeBytes == ProtocolConstants.FrameHeaderSize + ProtocolConstants.SlotPayloadCapacityBytes,
            "slotSizeBytes != headerSizeBytes + slotPayloadCapacityBytes");
        Require(ProtocolConstants.MapTotalSizeBytes == ProtocolConstants.SlotCount * ProtocolConstants.SlotSizeBytes,
            "mapTotalSizeBytes != slotCount * slotSizeBytes");
        Require(ProtocolConstants.SlotSizeBytes % ProtocolConstants.SlotAlignmentBytes == 0, "slotSizeBytes is not 64-byte aligned");
        Require(ProtocolConstants.SlotPayloadCapacityBytes == ProtocolConstants.MaxFrameWidth * ProtocolConstants.MaxFrameHeight * 4,
            "slotPayloadCapacityBytes != maxWidth * maxHeight * 4");

        return $"8 geometry constants + policy + 4 derived invariants match (mapTotalSizeBytes={ProtocolConstants.MapTotalSizeBytes})";
    }

    private static string D05()
    {
        var lifecycle = JsonNode.Parse(File.ReadAllText(Path.Combine(_contractsDir, "lifecycle_recovery_v1.json")))!;
        var states = (JsonArray)lifecycle["states"]!;

        foreach (var state in states)
        {
            var name = (string)state!["name"]!;
            var expected = ((JsonArray)state["validTransitions"]!).Select(t => (string)t!).OrderBy(t => t, StringComparer.Ordinal).ToList();
            var hostState = Enum.Parse<LifecycleState>(name);
            var actual = LifecycleStateMachine.ValidTransitions[hostState].Select(s => s.ToString()).OrderBy(t => t, StringComparer.Ordinal).ToList();
            Require(expected.SequenceEqual(actual),
                $"transition table for {name}: host=[{string.Join(", ", actual)}], catalog=[{string.Join(", ", expected)}]");
        }

        Require(states.Count == LifecycleStateMachine.ValidTransitions.Count,
            $"catalog declares {states.Count} states, host has {LifecycleStateMachine.ValidTransitions.Count}");

        // Behavioural guards that must agree with the frozen contract.
        var reconnect = new LifecycleStateMachine(LifecycleState.HANDSHAKING, isColdBoot: false);
        reconnect.ProtocolNegotiated = true;
        reconnect.CapabilitiesAccepted = true;
        reconnect.EngineBusinessReady = true;
        Require(!reconnect.TryTransitionTo(LifecycleState.READY, out var reconnectCode) && reconnectCode == ErrorCodes.InvalidStateTransition,
            "non-cold-boot HANDSHAKING -> READY was not rejected");

        var cold = new LifecycleStateMachine(LifecycleState.HANDSHAKING, isColdBoot: true);
        cold.ProtocolNegotiated = true;
        cold.CapabilitiesAccepted = true;
        cold.EngineBusinessReady = true;
        cold.NoRecoverableBusinessState = true;
        cold.TransitionTo(LifecycleState.READY);
        Require(cold.Current == LifecycleState.READY, "cold-boot HANDSHAKING -> READY did not succeed");

        var syncing = new LifecycleStateMachine(LifecycleState.SYNCING, isColdBoot: false);
        syncing.EngineBusinessReady = true;
        Require(!syncing.TryTransitionTo(LifecycleState.READY, out _), "SYNCING -> READY without a validated snapshot was not rejected");
        syncing.SnapshotResynced = true;
        syncing.TransitionTo(LifecycleState.READY);
        Require(syncing.Current == LifecycleState.READY, "SYNCING -> READY with snapshot + businessReady did not succeed");

        return $"{states.Count} lifecycle states and 4 behavioural READY-gate guards match the contract";
    }

    private static string D06()
    {
        var tracker = new SequenceTracker("session-a", "nonce-1", 1);
        tracker.CheckAndUpdate("engine", "session-a", "nonce-1", 0);

        // A new handshake resets the generation; sequence 0 must be accepted again.
        tracker.ResetGeneration("session-a", "nonce-2");
        Require(tracker.GenerationId == 2, $"generation id did not advance: {tracker.GenerationId}");
        var accepted = tracker.TryCheckAndUpdate("engine", "session-a", "nonce-2", 0, out var error);
        Require(accepted && error.Length == 0, $"sequence 0 was rejected in the new generation: {error}");
        Require(tracker.HighWater("engine", "session-a", "nonce-2") == 0, "new generation high-water is not 0");
        Require(tracker.HighWater("engine", "session-a", "nonce-1") == 0, "previous generation high-water was lost");

        var next = tracker.TryCheckAndUpdate("engine", "session-a", "nonce-2", 1, out _);
        Require(next, "sequence 1 was rejected after sequence 0 in the new generation");

        return "generation reset accepts sequence 0 in the new generation while preserving the old generation's high-water";
    }

    private static string D07()
    {
        var tracker = new SequenceTracker("session-a", "nonce-2", 2);
        tracker.CheckAndUpdate("engine", "session-a", "nonce-2", 0);
        tracker.CheckAndUpdate("engine", "session-a", "nonce-2", 1);

        var stale = tracker.TryCheckAndUpdate("engine", "session-a", "nonce-1", 999, out var staleError);
        Require(!stale && staleError == ErrorCodes.StaleGeneration,
            $"old-generation packet was not rejected with ERR_STALE_GENERATION (got accepted={stale}, code={staleError})");

        var foreign = tracker.TryCheckAndUpdate("engine", "session-b", "nonce-2", 1000, out var foreignError);
        Require(!foreign && foreignError == ErrorCodes.StaleSession,
            $"foreign-session packet was not rejected with ERR_STALE_SESSION (got accepted={foreign}, code={foreignError})");

        var replay = tracker.TryCheckAndUpdate("engine", "session-a", "nonce-2", 0, out var replayError);
        Require(!replay && replayError == ErrorCodes.StaleSequence,
            $"in-generation replay was not rejected with ERR_STALE_SEQUENCE (got accepted={replay}, code={replayError})");

        Require(tracker.HighWater("engine", "session-a", "nonce-2") == 1, "a rejected packet moved the high-water mark");

        return "old generation -> ERR_STALE_GENERATION, foreign session -> ERR_STALE_SESSION, replay -> ERR_STALE_SEQUENCE, high-water unchanged";
    }

    private static string D08()
    {
        // Oversize length prefix.
        var oversize = new byte[4];
        BitConverter.TryWriteBytes(oversize, (uint)(ProtocolConstants.MaxMessageBytes + 1));
        var oversizeRejected = false;
        try
        {
            Framing.ReadFramed(new MemoryStream(oversize));
        }
        catch (ProtocolViolationException ex)
        {
            oversizeRejected = ex.ErrorCode == ErrorCodes.MessageTooLarge;
        }
        Require(oversizeRejected, "an oversize declared length was not rejected with ERR_MESSAGE_TOO_LARGE");

        // Truncated body.
        var truncated = new byte[4 + 10];
        BitConverter.TryWriteBytes(truncated, 100u);
        var truncatedRejected = false;
        try
        {
            Framing.ReadFramed(new MemoryStream(truncated));
        }
        catch (ProtocolViolationException ex)
        {
            truncatedRejected = ex.ErrorCode == ErrorCodes.IncompleteFrame;
        }
        Require(truncatedRejected, "a truncated body was not rejected with ERR_INCOMPLETE_FRAME");

        // Truncated prefix.
        var shortPrefixRejected = false;
        try
        {
            Framing.ReadFramed(new MemoryStream(new byte[] { 1, 2 }));
        }
        catch (ProtocolViolationException ex)
        {
            shortPrefixRejected = ex.ErrorCode == ErrorCodes.IncompleteFrame;
        }
        Require(shortPrefixRejected, "a truncated length prefix was not rejected with ERR_INCOMPLETE_FRAME");

        // Clean EOF.
        Require(Framing.ReadFramed(new MemoryStream(Array.Empty<byte>())) is null, "clean EOF did not return null");

        // Round trip of a real framed envelope.
        var envelope = Envelope.Create("s", MessageTypes.Heartbeat, "r", 0, 123,
            new JsonObject { ["timestamp"] = 1.0, ["state"] = "HEALTHY" });
        var framed = Framing.FrameEnvelope(envelope);
        Require(BitConverter.ToUInt32(framed, 0) == framed.Length - 4, "length prefix does not equal the payload length");
        var decoded = Framing.ReadEnvelope(new MemoryStream(framed));
        Require(decoded is not null && decoded.MessageType == MessageTypes.Heartbeat && decoded.Sequence == 0,
            "framed envelope did not round-trip");

        return "oversize / truncated prefix / truncated body / clean EOF all handled, and a framed envelope round-trips";
    }

    private static string D09(string metricsPath)
    {
        var metrics = LoadMetrics(metricsPath);
        var names = new[] { "processExitDetectionMs", "processRestartMs", "handshakeMs", "snapshotResyncMs", "mockBusinessReadyMs" };
        var summary = (JsonObject)metrics["summary"]!;
        foreach (var name in names)
        {
            Require(summary.ContainsKey(name), $"metrics summary is missing '{name}'");
            var stat = (JsonObject)summary[name]!;
            foreach (var statName in new[] { "min", "median", "max", "sampleCount" })
            {
                Require(stat.ContainsKey(statName), $"metrics '{name}' is missing '{statName}'");
            }
            Require((int?)stat["sampleCount"] >= 1, $"metrics '{name}' has no samples");
        }

        Require(summary.ContainsKey("sampleCount"), "metrics summary is missing the run count");
        Require((int?)summary["sampleCount"] >= 5, $"metrics were collected over fewer than 5 runs: {summary["sampleCount"]}");

        // P95 may only appear when a metric has at least 20 independent samples.
        foreach (var name in names)
        {
            var stat = (JsonObject)summary[name]!;
            if (stat.ContainsKey("p95"))
            {
                Require((int?)stat["sampleCount"] >= 20,
                    $"metrics '{name}' reports p95 with only {stat["sampleCount"]} samples");
            }
        }

        return $"5 metrics are reported separately over {(int?)summary["sampleCount"]} runs, no premature p95";
    }

    private static string D10(string metricsPath)
    {
        var metrics = LoadMetrics(metricsPath);
        var summary = (JsonObject)metrics["summary"]!;

        var businessReady = summary["businessReadyMs"];
        Require(businessReady is null, $"metrics must not carry a numeric businessReadyMs, found {businessReady?.ToJsonString()}");

        Require(summary.ContainsKey("businessReadyStatus"), "metrics are missing businessReadyStatus");
        Require((string?)summary["businessReadyStatus"] == "NOT_MEASURED",
            $"businessReadyStatus must be NOT_MEASURED, found {summary["businessReadyStatus"]}");

        Require(summary.ContainsKey("mockBusinessReadyMs"), "metrics are missing mockBusinessReadyMs");
        var mock = (JsonObject)summary["mockBusinessReadyMs"]!;
        Require(mock["median"] is not null, "mockBusinessReadyMs has no median value");

        // The same rule must hold for every raw run sample.
        var raw = (JsonArray)metrics["raw"]!;
        foreach (var run in raw)
        {
            var obj = (JsonObject)run!;
            Require(!obj.ContainsKey("businessReadyMs"), $"raw run {obj["run"]} carries a businessReadyMs key");
        }

        return "businessReadyMs is absent/never numeric, businessReadyStatus=NOT_MEASURED, mockBusinessReadyMs is the only populated readiness metric";
    }

    private static JsonObject LoadMetrics(string metricsPath)
    {
        if (string.IsNullOrEmpty(metricsPath))
        {
            throw new InvalidOperationException(
                "no --metrics artifact supplied; D09/D10 assert on the real supervisor metrics output and will not pass on an absent artifact");
        }
        if (!File.Exists(metricsPath))
        {
            throw new FileNotFoundException($"metrics artifact not found: {metricsPath}");
        }
        var node = JsonNode.Parse(File.ReadAllText(metricsPath)) as JsonObject
                   ?? throw new InvalidDataException($"metrics artifact is not a JSON object: {metricsPath}");

        // The artifact may be the raw NteHost scenario result (which nests the
        // metrics under "run") or an already-extracted metrics object.
        if (node["summary"] is null && node["run"] is JsonObject run)
        {
            return run;
        }
        return node;
    }

    private static void Require(bool condition, string message)
    {
        if (!condition)
        {
            throw new InvalidOperationException(message);
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
}
