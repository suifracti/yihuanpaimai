using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text.Json.Nodes;
using System.Threading;
using NteHost.Protocol;

namespace NteHost;

public sealed class GenerationRecord
{
    public int GenerationId { get; set; }
    public string Nonce { get; set; } = string.Empty;
    public string PipeName { get; set; } = string.Empty;
    public string MapName { get; set; } = string.Empty;
    public bool ColdBoot { get; set; }
    public int ChildPid { get; set; }
    public bool PipeAccepted { get; set; }
    public bool HelloAckValidated { get; set; }
    public string EngineReadiness { get; set; } = string.Empty;
    public bool EngineBusinessReady { get; set; }
    public long EngineFirstSequence { get; set; } = -1;
    public long HostHelloSequence { get; set; } = -1;
    public double? HandshakeMs { get; set; }
    public double? MockBusinessReadyMs { get; set; }
    public double? SnapshotResyncMs { get; set; }
    public double? ProcessExitDetectionMs { get; set; }
    public double? ProcessRestartMs { get; set; }
    public string FinalState { get; set; } = string.Empty;
    public string HelloWireHex { get; set; } = string.Empty;
    public string HelloAckWireHex { get; set; } = string.Empty;
    public string HelloAckStatus { get; set; } = string.Empty;
}

/// <summary>
/// Owns exactly one Host-side supervision session: one stable sessionId, a fresh
/// nonce per child generation, one Named Pipe, one fixed-v1 MMF, one Job Object.
/// </summary>
public sealed class SupervisorSession : IDisposable
{
    public sealed class Options
    {
        public string PythonExe { get; set; } = string.Empty;
        public string EngineScript { get; set; } = string.Empty;
        public string WorkDir { get; set; } = string.Empty;
        public string? ContractsDir { get; set; }
        public string SessionId { get; set; } = string.Empty;
        public TraceLog? Trace { get; set; }
        public string EngineFault { get; set; } = string.Empty;
        public string? EngineFaultCapability { get; set; }
        public string? EngineFaultHelloSize { get; set; }
        public string? EngineLogPath { get; set; }
        public string PipeNameOverride { get; set; } = string.Empty;
        public int AcceptTimeoutMs { get; set; } = 15000;
        public int PostAcceptDelayMs { get; set; } = 0;
    }

    private readonly Options _options;
    private readonly MessageCatalog _catalog;
    private readonly CapabilityContract _capabilities;
    private readonly JobObjectGuard _job;
    private readonly TraceLog _trace;
    private BlockingCollection<Envelope> _inbox = new();
    private readonly List<GenerationRecord> _generations = new();
    private readonly List<string> _errors = new();

    private Thread? _pump;
    private long _pipeEofNs;
    private string _pipeEofReason = string.Empty;

    public LifecycleStateMachine Lifecycle { get; }
    public SequenceTracker EngineSequences { get; private set; } = null!;
    public SequenceTracker HostSequences { get; private set; } = null!;
    public MmfRingGuard Mmf { get; } = new();
    public IReadOnlyList<GenerationRecord> Generations => _generations;
    public IReadOnlyList<string> Errors => _errors;
    public PipeSecurityFacts? PipeFacts => _pipe?.SecurityFacts;
    public int GenerationId { get; private set; }
    public string Nonce { get; private set; } = string.Empty;
    public string MapName { get; private set; } = string.Empty;
    public string PipeName { get; private set; } = string.Empty;
    public bool ShutdownRequested { get; private set; }
    public bool CrashCounted { get; private set; }
    public long? CrashMarkerNs { get; private set; }
    public long? ExitDetectedNs { get; private set; }
    public string ExitDetectionSignal { get; private set; } = string.Empty;
    public int? ExitCode { get; private set; }
    public long ChildSpawnNs { get; private set; }
    public int? ChildPid { get; private set; }
    public bool JobKillOnCloseSet => _job.KillOnJobCloseSet;
    public bool ChildAlive => _child is { HasExited: false };
    public bool PipeConnectFailedClosed { get; private set; }
    public string PipeConnectFailureCode { get; private set; } = string.Empty;
    public string PipeAbortAction { get; private set; } = string.Empty;
    public bool StdioUsedAsProtocolTransport { get; private set; }
    public bool PipeAbortObserved => _pipeEofNs != 0;
    public string PipeAbortReason => _pipeEofReason;
    public long HostHelloSequence { get; private set; }
    public long HostHeartbeatSequence { get; private set; }
    public string LastSnapshotRequestId { get; private set; } = string.Empty;
    public string LastSnapshotCorrelationId { get; private set; } = string.Empty;

    /// <summary>
    /// Validates an inbound operational payload against the catalog before it is
    /// consumed, so an engine that drifts from the frozen schema fails closed
    /// instead of being silently accepted.
    /// </summary>
    private void ValidateInbound(Envelope envelope)
    {
        switch (envelope.MessageType)
        {
            case MessageTypes.HelloAck:
            case MessageTypes.StateSnapshot:
            case MessageTypes.CommandResult:
            case MessageTypes.Heartbeat:
            case MessageTypes.Error:
                _catalog.ValidatePayload(envelope.MessageType, envelope.Payload);
                break;
        }
    }
    public long HostRequestCounter { get; private set; }

    public SupervisorSession(Options options)
    {
        _options = options;
        _catalog = MessageCatalog.Load(options.ContractsDir, AppContext.BaseDirectory);
        _capabilities = CapabilityContract.Load(options.ContractsDir, AppContext.BaseDirectory);
        _job = new JobObjectGuard();
        // Never null: a TraceLog with no path is a valid no-op sink, so callers do
        // not have to guard every event.
        _trace = options.Trace ?? new TraceLog(null, options.SessionId, "init");
        Lifecycle = new LifecycleStateMachine(LifecycleState.ENGINE_DOWN, isColdBoot: true);
        HostSequences = new SequenceTracker(options.SessionId, "bootstrap", 0);
        EngineSequences = new SequenceTracker(options.SessionId, "bootstrap", 0);
    }

    public string ContractsDirectory => _catalog.SourcePath;
    public MessageCatalog Catalog => _catalog;
    public CapabilityContract Capabilities => _capabilities;

    private PipeControlChannel? _pipe;
    private Process? _child;

    // ---------------------------------------------------------------- generation

    public GenerationRecord StartGeneration(bool coldBoot, string? pipeNameOverride = null, bool spawnChild = true)
    {
        GenerationId += 1;
        Nonce = NewNonce();
        PipeName = string.IsNullOrEmpty(pipeNameOverride) ? ProtocolConstants.PipeName(_options.SessionId, Nonce) : pipeNameOverride;
        MapName = ProtocolConstants.MapName(_options.SessionId, Nonce);

        // Each generation gets its own pipe-EOF bookkeeping; a previous
        // generation's EOF must never leak into the new one.
        _pipeEofNs = 0;
        _pipeEofReason = string.Empty;
        ExitDetectedNs = null;
        ExitDetectionSignal = string.Empty;
        ExitCode = null;

        _trace.SetGenerationNonce(Nonce);
        _trace.Event("generation.start", GenerationId, new { coldBoot, nonceShort = Nonce[..8], pipeName = PipeName, mapName = MapName });

        var record = new GenerationRecord
        {
            GenerationId = GenerationId,
            Nonce = Nonce,
            PipeName = PipeName,
            MapName = MapName,
            ColdBoot = coldBoot,
        };
        _generations.Add(record);

        // 1. Job Object already owns KILL_ON_JOB_CLOSE for the whole Host lifetime.
        // 2. Real fixed-v1 MMF for this generation (created, zero-initialised, never written to).
        Mmf.Create(GenerationId, _options.SessionId, Nonce);

        // 3. Named Pipe (single transport, no stdio fallback).
        _pipe = PipeControlChannel.Create(_options.SessionId, Nonce);

        if (spawnChild)
        {
            StartChild();
            record.ChildPid = ChildPid ?? -1;
        }

        return record;
    }

    private void StartChild()
    {
        var args = new List<string>
        {
            "-u",
            _options.EngineScript,
            "--session-id", _options.SessionId,
            "--nonce", Nonce,
            "--pipe-name", PipeName,
            "--frame-buffer-name", MapName,
            "--frame-buffer-size", ProtocolConstants.MapTotalSizeBytes.ToString(),
            "--work-dir", _options.WorkDir,
            "--generation-id", GenerationId.ToString(),
        };
        if (!string.IsNullOrEmpty(_options.EngineLogPath))
        {
            args.Add("--log");
            args.Add(_options.EngineLogPath!);
        }
        if (!string.IsNullOrEmpty(_options.EngineFault))
        {
            args.Add("--fault");
            args.Add(_options.EngineFault);
        }
        if (!string.IsNullOrEmpty(_options.EngineFaultCapability))
        {
            args.Add("--fault-missing-mandatory-capability");
            args.Add(_options.EngineFaultCapability!);
        }
        if (!string.IsNullOrEmpty(_options.EngineFaultHelloSize))
        {
            args.Add("--fault-hello-size");
            args.Add(_options.EngineFaultHelloSize!);
        }

        var psi = new ProcessStartInfo
        {
            FileName = _options.PythonExe,
            WorkingDirectory = _options.WorkDir,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,   // logs only - never the protocol transport
            RedirectStandardError = true,    // logs only - never the protocol transport
        };
        foreach (var arg in args)
        {
            psi.ArgumentList.Add(arg);
        }

        var process = new Process { StartInfo = psi, EnableRaisingEvents = true };
        process.Exited += OnChildExited;
        var spawnStartNs = ProtocolClock.NowNs();
        process.Start();
        ChildSpawnNs = ProtocolClock.NowNs();
        _child = process;
        ChildPid = process.Id;
        _trace.Event("child.spawned", GenerationId, new { pid = process.Id, spawnMs = ProtocolClock.DeltaMs(spawnStartNs, ChildSpawnNs) });

        // Drain stdout/stderr into the trace: these are logs, not protocol.
        process.OutputDataReceived += (_, e) => { if (e.Data is not null) _trace.Event("child.stdout", GenerationId, new { line = e.Data }); };
        process.ErrorDataReceived += (_, e) => { if (e.Data is not null) _trace.Event("child.stderr", GenerationId, new { line = e.Data }); };
        process.BeginOutputReadLine();
        process.BeginErrorReadLine();

        if (!_job.Assign(process))
        {
            _errors.Add($"AssignProcessToJobObject failed for pid {process.Id}");
        }
    }

    private void OnChildExited(object? sender, EventArgs e)
    {
        var ns = ProtocolClock.NowNs();
        if (ExitDetectedNs is null || ns < ExitDetectedNs)
        {
            ExitDetectedNs = ns;
            ExitDetectionSignal = "process_exited";
        }
        try
        {
            ExitCode = ((Process)sender!).ExitCode;
        }
        catch
        {
            ExitCode = null;
        }
    }

    /// <summary>
    /// Tears down the live generation's transport before a new one is allocated.
    /// Order matters: close the pipe first so the reader thread unblocks, join it,
    /// and only then dispose the inbox it was feeding; finally release the
    /// generation's shared-memory mapping.
    /// </summary>
    public MmfGenerationRecord CloseCurrentGeneration()
    {
        _pipe?.Dispose();
        _pipe = null;
        _pump?.Join(3000);
        try
        {
            _inbox.CompleteAdding();
        }
        catch (ObjectDisposedException)
        {
            // already completed
        }
        _inbox.Dispose();
        _inbox = new BlockingCollection<Envelope>();
        return Mmf.DisposeGeneration(GenerationId);
    }

    public void BeginAccept()
    {
        _pipe!.BeginAccept(TimeSpan.FromMilliseconds(_options.AcceptTimeoutMs), _trace, GenerationId);
        StartPump(_pipe.Stream, _inbox);
    }

    /// <summary>
    /// Reader thread for one generation. The stream and inbox are captured as
    /// parameters so that a superseded generation's pump keeps reading (and then
    /// exits on) its own stream instead of following the field to the next
    /// generation's pipe.
    /// </summary>
    private void StartPump(Stream stream, BlockingCollection<Envelope> inbox)
    {
        var generationId = GenerationId;
        _pump = new Thread(() =>
        {
            try
            {
                while (true)
                {
                    var envelope = Framing.ReadEnvelope(stream);
                    if (envelope is null)
                    {
                        _pipeEofNs = ProtocolClock.NowNs();
                        _pipeEofReason = ErrorCodes.StreamEof;
                        break;
                    }
                    // Every inbound message is traced with its correlation keys so a
                    // request can be followed across both process logs.
                    _trace.Event("pipe.receive", generationId, new
                    {
                        messageType = envelope.MessageType,
                        requestId = envelope.RequestId,
                        sequence = envelope.Sequence,
                    }, envelope.RequestId, envelope.CorrelationId);
                    try
                    {
                        inbox.Add(envelope);
                    }
                    catch (Exception)
                    {
                        break;
                    }
                }
            }
            catch (Exception ex)
            {
                _pipeEofNs = ProtocolClock.NowNs();
                _pipeEofReason = ex is ProtocolViolationException pve ? pve.ErrorCode : ErrorCodes.PipeBroken;
                _trace.Event("pipe.eof", generationId, new { reason = _pipeEofReason, message = ex.Message });
            }
            finally
            {
                try
                {
                    inbox.CompleteAdding();
                }
                catch (ObjectDisposedException)
                {
                    // the generation was torn down; nothing to complete
                }
            }
        })
        {
            IsBackground = true,
            Name = "nte-pipe-pump",
        };
        _pump.Start();
    }

    public Envelope? WaitForMessage(Func<Envelope, bool> predicate, int timeoutMs, out List<Envelope> observed)
    {
        observed = new List<Envelope>();
        var deadline = Environment.TickCount64 + timeoutMs;
        while (true)
        {
            var remaining = (int)(deadline - Environment.TickCount64);
            if (remaining <= 0)
            {
                return null;
            }
            Envelope envelope;
            try
            {
                if (!_inbox.TryTake(out envelope!, remaining))
                {
                    return null;
                }
            }
            catch (InvalidOperationException)
            {
                return null;
            }
            observed.Add(envelope);
            if (predicate(envelope))
            {
                return envelope;
            }
        }
    }

    // ---------------------------------------------------------------- handshake

    public GenerationRecord Handshake(bool coldBoot)
    {
        var record = _generations[^1];
        record.ColdBoot = coldBoot;

        Lifecycle.TryTransitionTo(LifecycleState.STARTING, out _);
        var acceptNs = ProtocolClock.NowNs();

        BeginAccept();
        record.PipeAccepted = true;

        if (_options.PostAcceptDelayMs > 0)
        {
            Thread.Sleep(_options.PostAcceptDelayMs);
        }

        Lifecycle.TryTransitionTo(LifecycleState.HANDSHAKING, out _);

        // ---- HELLO -------------------------------------------------------
        HostSequences.ResetGeneration(_options.SessionId, Nonce);
        var helloSequence = coldBoot ? 1 : 0;
        HostHelloSequence = helloSequence;
        record.HostHelloSequence = helloSequence;
        var hello = BuildHello(helloSequence);
        var helloFramed = Framing.FrameEnvelope(hello);
        record.HelloWireHex = Json.Hex(helloFramed);
        _trace.Event("pre_hello_probe", GenerationId, new
        {
            childAlive = _child is { HasExited: false },
            childPid = ChildPid,
            pipeEofObserved = _pipeEofNs != 0,
            pipeEofReason = _pipeEofReason,
            framedBytes = helloFramed.Length,
        });
        _pipe!.Send(hello, _trace, GenerationId);

        var ack = WaitForMessage(e => e.MessageType == MessageTypes.HelloAck || e.MessageType == MessageTypes.Error,
            ProtocolConstants.HelloNegotiationTimeoutMs, out var observed);
        if (ack is null)
        {
            throw new ProtocolViolationException(ErrorCodes.HandshakeTimeout,
                $"no HELLO_ACK within {ProtocolConstants.HelloNegotiationTimeoutMs}ms (observed {observed.Count} messages)");
        }

        if (ack.MessageType == MessageTypes.Error)
        {
            var code = (string?)ack.Payload["errorCode"] ?? ErrorCodes.SchemaValidationFailed;
            throw new ProtocolViolationException(code, $"engine rejected HELLO: {ack.Payload.ToJsonString()}");
        }

        record.HelloAckWireHex = Json.Hex(Framing.FrameEnvelope(ack));
        var ackPayload = (JsonObject)ack.Payload;
        record.HelloAckStatus = (string?)ackPayload["status"] ?? string.Empty;

        // Engine sequence in a new generation legitimately restarts at 0.
        EngineSequences.ResetGeneration(_options.SessionId, Nonce);
        EngineSequences.CheckAndUpdate("engine", ack.SessionId, Nonce, ack.Sequence);
        record.EngineFirstSequence = ack.Sequence;

        _catalog.ValidatePayload(MessageTypes.HelloAck, ackPayload);

        var readinessEnum = ReadinessEnum();
        if (record.HelloAckStatus == "ACCEPTED")
        {
            MessageCatalog.ValidateHelloAckReadiness(ackPayload, readinessEnum);
            record.EngineReadiness = (string?)ackPayload["readiness"] ?? string.Empty;
            record.EngineBusinessReady = (bool?)ackPayload["engineBusinessReady"] ?? false;
            Lifecycle.ProtocolNegotiated = true;
            Lifecycle.CapabilitiesAccepted = true;
            Lifecycle.EngineBusinessReady = record.EngineBusinessReady;
        }
        else
        {
            Lifecycle.CapabilitiesAccepted = false;
            Lifecycle.EngineBusinessReady = false;
        }

        record.HelloAckValidated = true;
        var ackNs = ProtocolClock.NowNs();
        record.HandshakeMs = ProtocolClock.DeltaMs(acceptNs, ackNs);
        record.MockBusinessReadyMs = ProtocolClock.DeltaMs(ChildSpawnNs, ackNs);
        _trace.Event("handshake.complete", GenerationId,
            new { status = record.HelloAckStatus, readiness = record.EngineReadiness, handshakeMs = record.HandshakeMs },
            hello.RequestId, ack.CorrelationId);
        return record;
    }

    private Envelope BuildHello(long sequence)
    {
        var payload = new JsonObject
        {
            ["hostVersion"] = "2.1.0-v2-1",
            ["supportedProtocols"] = new JsonArray { ProtocolConstants.ProtocolVersion },
            ["sessionNonce"] = Nonce,
            ["capabilities"] = _capabilities.BuildAdvertisement(),
            ["frameBufferName"] = MapName,
            ["frameBufferSize"] = ProtocolConstants.MapTotalSizeBytes,
        };
        var declared = _options.EngineFaultHelloSize;
        if (!string.IsNullOrEmpty(declared) && long.TryParse(declared, out var overrideSize))
        {
            // Test-only fault injection (T18): declare a size the fixed-v1 geometry
            // cannot accept so the engine's fail-closed path is exercised for real.
            payload["frameBufferSize"] = overrideSize;
        }

        return Envelope.Create(
            _options.SessionId,
            MessageTypes.Hello,
            NextRequestId("req-hello"),
            sequence,
            ProtocolClock.NowNs(),
            payload,
            correlationId: NextRequestId("corr-hello"));
    }

    private IReadOnlyList<string> ReadinessEnum()
    {
        var contract = _catalog.ReadinessContract;
        var values = new List<string>();
        foreach (var value in (JsonArray)contract["enum"]!)
        {
            values.Add((string)value!);
        }
        return values;
    }

    // ---------------------------------------------------------------- readiness

    /// <summary>
    /// Cold boot may go HANDSHAKING -> READY directly, but only with
    /// noRecoverableBusinessState == true. Reconnect MUST pass through SYNCING.
    /// </summary>
    public void ReachReady(bool coldBoot, bool noRecoverableBusinessState)
    {
        var record = _generations[^1];
        if (coldBoot)
        {
            Lifecycle.NoRecoverableBusinessState = noRecoverableBusinessState;
            Lifecycle.SnapshotResynced = false;
            Lifecycle.TransitionTo(LifecycleState.READY);
            _trace.Event("lifecycle.ready.coldboot", GenerationId, new
            {
                isColdBoot = Lifecycle.IsColdBoot,
                noRecoverableBusinessState,
                engineBusinessReady = Lifecycle.EngineBusinessReady,
                protocolNegotiated = Lifecycle.ProtocolNegotiated,
                capabilitiesAccepted = Lifecycle.CapabilitiesAccepted,
            });
            record.FinalState = Lifecycle.Current.ToString();
            return;
        }

        Lifecycle.NoRecoverableBusinessState = false;
        Lifecycle.TransitionTo(LifecycleState.SYNCING);
        var requestId = NextRequestId("req-snapshot");
        var request = Envelope.Create(
            _options.SessionId,
            MessageTypes.StateSnapshotRequest,
            requestId,
            NextHostSequence(),
            ProtocolClock.NowNs(),
            new JsonObject { ["includeDrafts"] = true },
            correlationId: NextRequestId("corr-snapshot"));

        var sentNs = ProtocolClock.NowNs();
        _pipe!.Send(request, _trace, GenerationId);
        LastSnapshotRequestId = request.RequestId;

        var snapshot = WaitForMessage(e => e.MessageType == MessageTypes.StateSnapshot || e.MessageType == MessageTypes.Error,
            ProtocolConstants.HelloNegotiationTimeoutMs, out _);
        if (snapshot is null)
        {
            throw new ProtocolViolationException(ErrorCodes.StreamEof, "no STATE_SNAPSHOT received during resync");
        }
        if (snapshot.MessageType == MessageTypes.Error)
        {
            throw new ProtocolViolationException((string?)snapshot.Payload["errorCode"] ?? ErrorCodes.SchemaValidationFailed,
                "engine failed the resync request");
        }

        ValidateInbound(snapshot);
        EngineSequences.CheckAndUpdate("engine", snapshot.SessionId, Nonce, snapshot.Sequence);
        _catalog.ValidateStateSnapshot(snapshot, _options.SessionId);
        LastSnapshotCorrelationId = snapshot.CorrelationId ?? string.Empty;

        if (!string.Equals(snapshot.CorrelationId, request.RequestId, StringComparison.Ordinal))
        {
            throw new ProtocolViolationException(ErrorCodes.MalformedEnvelope,
                $"STATE_SNAPSHOT correlationId '{snapshot.CorrelationId}' does not echo requestId '{request.RequestId}'");
        }

        var businessReady = (bool?)snapshot.Payload["businessReady"] ?? false;
        Lifecycle.EngineBusinessReady = Lifecycle.EngineBusinessReady && businessReady;
        Lifecycle.SnapshotResynced = true;
        Lifecycle.TransitionTo(LifecycleState.READY);

        record.SnapshotResyncMs = ProtocolClock.DeltaMs(sentNs, ProtocolClock.NowNs());
        record.FinalState = Lifecycle.Current.ToString();
        _trace.Event("lifecycle.ready.resynced", GenerationId,
            new { snapshotResyncMs = record.SnapshotResyncMs, snapshotSequence = snapshot.Sequence },
            request.RequestId, snapshot.CorrelationId);
    }

    // ---------------------------------------------------------------- runtime

    public void HeartbeatRound()
    {
        if (!TryHeartbeatRound(out var errorCode))
        {
            throw new ProtocolViolationException(errorCode, $"heartbeat round failed with {errorCode}");
        }
    }

    /// <summary>
    /// One heartbeat round. Returns false with the catalog error code instead of
    /// throwing so the caller can drive the DEGRADED transition deterministically.
    /// </summary>
    public bool TryHeartbeatRound(out string errorCode)
    {
        var request = Envelope.Create(
            _options.SessionId,
            MessageTypes.Heartbeat,
            NextRequestId("hb"),
            NextHostSequence(),
            ProtocolClock.NowNs(),
            new JsonObject { ["timestamp"] = ProtocolClock.NowNs() / 1_000_000_000.0, ["state"] = "HEALTHY" },
            correlationId: NextRequestId("corr-hb"));
        _pipe!.Send(request, _trace, GenerationId);

        var reply = WaitForMessage(e => e.MessageType == MessageTypes.Heartbeat, ProtocolConstants.HeartbeatTimeoutMs, out _);
        if (reply is null)
        {
            errorCode = ErrorCodes.HeartbeatTimeout;
            return false;
        }
        ValidateInbound(reply);
        if (!EngineSequences.TryCheckAndUpdate("engine", reply.SessionId, Nonce, reply.Sequence, out errorCode))
        {
            return false;
        }
        errorCode = string.Empty;
        return true;
    }

    public Envelope SendCommand(string action, JsonObject? parameters = null, int timeoutMs = 3000)
    {
        var commandId = Guid.NewGuid().ToString();
        var request = Envelope.Create(
            _options.SessionId,
            MessageTypes.Command,
            NextRequestId("cmd"),
            NextHostSequence(),
            ProtocolClock.NowNs(),
            new JsonObject
            {
                ["commandId"] = commandId,
                ["action"] = action,
                ["parameters"] = parameters ?? new JsonObject(),
                ["expiresAtNs"] = ProtocolClock.NowNs() + 60L * 1_000_000_000L,
            },
            correlationId: NextRequestId("corr-cmd"));
        _pipe!.Send(request, _trace, GenerationId);

        var result = WaitForMessage(e => e.MessageType == MessageTypes.CommandResult || e.MessageType == MessageTypes.Error, timeoutMs, out _);
        if (result is not null)
        {
            ValidateInbound(result);
            EngineSequences.TryCheckAndUpdate("engine", result.SessionId, Nonce, result.Sequence, out _);
        }
        return result ?? request;
    }

    /// <summary>
    /// Crash probe: the child writes a crash marker in the shared QPC domain and
    /// then exits fatally. processExitDetectionMs is the crash-marker-to-detection
    /// end-to-end latency, not a bare OS event dispatch figure.
    /// </summary>
    public GenerationRecord CrashAndMeasure()
    {
        var record = _generations[^1];
        CrashMarkerNs = null;
        ExitDetectedNs = null;
        ExitDetectionSignal = string.Empty;

        SendCommand("test.simulate_crash", timeoutMs: 2000);

        var markerPath = Path.Combine(_options.WorkDir, "crash_marker.json");
        var deadline = Environment.TickCount64 + 5000;
        while (Environment.TickCount64 < deadline)
        {
            if (ExitDetectedNs is not null && File.Exists(markerPath))
            {
                break;
            }
            Thread.Sleep(2);
        }

        if (File.Exists(markerPath))
        {
            var node = JsonNode.Parse(File.ReadAllText(markerPath));
            CrashMarkerNs = (long?)node?["crashMarkerNs"];
        }

        if (ExitDetectedNs is null)
        {
            // Fall back to the pipe EOF signal if the process-exited event was lost.
            if (_pipeEofNs != 0)
            {
                ExitDetectedNs = _pipeEofNs;
                ExitDetectionSignal = _pipeEofReason;
            }
        }

        if (CrashMarkerNs is not null && ExitDetectedNs is not null && ExitDetectedNs > CrashMarkerNs)
        {
            record.ProcessExitDetectionMs = ProtocolClock.DeltaMs(CrashMarkerNs.Value, ExitDetectedNs.Value);
        }
        else
        {
            record.ProcessExitDetectionMs = null;
        }

        record.FinalState = Lifecycle.Current.ToString();
        _trace.Event("crash.detected", GenerationId, new
        {
            crashMarkerNs = CrashMarkerNs,
            exitDetectedNs = ExitDetectedNs,
            signal = ExitDetectionSignal,
            exitCode = ExitCode,
            processExitDetectionMs = record.ProcessExitDetectionMs,
        });
        return record;
    }

    public void TransitionToEngineDownOnCrash()
    {
        ShutdownRequested = false;
        CrashCounted = true;
        Lifecycle.TransitionTo(LifecycleState.ENGINE_DOWN);
    }

    /// <summary>
    /// Restart: tear down the dead generation's pipe and MMF, then spawn a fresh
    /// generation with a new nonce / pipe / map. processRestartMs covers detection
    /// to the new child's Start() returning, and excludes the handshake.
    /// </summary>
    public GenerationRecord RestartAndMeasure()
    {
        var restartStartNs = ExitDetectedNs ?? ProtocolClock.NowNs();

        // Drain and close the stale generation handles before allocating new ones.
        var closedGeneration = GenerationId;
        CloseCurrentGeneration();

        var record = StartGeneration(coldBoot: false);
        record.ProcessRestartMs = ProtocolClock.DeltaMs(restartStartNs, ChildSpawnNs);
        _trace.Event("restart.complete", GenerationId, new
        {
            processRestartMs = record.ProcessRestartMs,
            newNonceShort = Nonce[..8],
            newMapName = MapName,
            oldGeneration = closedGeneration,
        });
        return record;
    }

    /// <summary>
    /// Controlled shutdown: protocol 1.0.0 has NO shutdown ACK. The Host sends
    /// ENGINE_SHUTDOWN and waits for the child to exit gracefully; on timeout it
    /// uses the explicit Job Object termination path. A shutdownRequested exit is
    /// never counted as a crash.
    /// </summary>
    public Dictionary<string, object?> ControlledShutdown()
    {
        var result = new Dictionary<string, object?>();
        var record = _generations[^1];
        ShutdownRequested = true;
        CrashCounted = false;

        var request = Envelope.Create(
            _options.SessionId,
            MessageTypes.EngineShutdown,
            NextRequestId("req-shutdown"),
            NextHostSequence(),
            ProtocolClock.NowNs(),
            new JsonObject { ["reason"] = "host_shutdown", ["timeoutMs"] = ProtocolConstants.ShutdownTimeoutMs });

        var sentNs = ProtocolClock.NowNs();
        var sent = false;
        try
        {
            _pipe!.Send(request, _trace, GenerationId);
            sent = true;
        }
        catch (Exception ex)
        {
            result["sendError"] = ex.Message;
        }

        var graceful = false;
        var terminatedByJob = false;
        if (_child is not null)
        {
            try
            {
                graceful = _child.WaitForExit(ProtocolConstants.ShutdownTimeoutMs);
            }
            catch (Exception ex)
            {
                result["waitError"] = ex.Message;
            }

            if (!graceful)
            {
                terminatedByJob = _job.Terminate(1);
                try
                {
                    _child.WaitForExit(2000);
                }
                catch
                {
                    // ignored - the terminate path already ran
                }
            }
        }

        result["shutdownMessageSent"] = sent;
        result["awaitedShutdownAck"] = false;
        result["gracefulExitWithin2000ms"] = graceful;
        result["explicitTerminateUsed"] = terminatedByJob;
        result["shutdownMs"] = ProtocolClock.DeltaMs(sentNs, ProtocolClock.NowNs());
        result["countedAsCrash"] = CrashCounted;
        result["shutdownRequested"] = ShutdownRequested;
        result["childExitCode"] = ExitCode;

        if (Lifecycle.Current is LifecycleState.READY or LifecycleState.DEGRADED or LifecycleState.SYNCING)
        {
            Lifecycle.TransitionTo(LifecycleState.ENGINE_DOWN);
        }
        record.FinalState = Lifecycle.Current.ToString();

        _trace.Event("shutdown.complete", GenerationId, result, request.RequestId);
        return result;
    }

    // ---------------------------------------------------------------- generation proofs

    /// <summary>
    /// T10 pair: a brand-new generation's sequence 0 must be ACCEPTED, and a packet
    /// carrying the previous generation's nonce must fail closed with
    /// ERR_STALE_GENERATION. Proving only one half is not a pass.
    /// </summary>
    public Dictionary<string, object?> ProveGenerationReset(string oldNonce, string foreignSessionId)
    {
        var proof = new Dictionary<string, object?>();

        // (A) new generation, sequence 0 - accepted
        var tracker = new SequenceTracker(_options.SessionId, Nonce, GenerationId);
        var accepted = tracker.TryCheckAndUpdate("engine", _options.SessionId, Nonce, 0, out var acceptError);
        proof["newGenerationSequence"] = 0;
        proof["newGenerationAccepted"] = accepted;
        proof["newGenerationErrorCode"] = acceptError;
        proof["newGenerationHighWater"] = tracker.HighWater("engine", _options.SessionId, Nonce);

        // (A2) the very next sequence is accepted too, and a replay of 0 is stale
        var second = tracker.TryCheckAndUpdate("engine", _options.SessionId, Nonce, 1, out var secondError);
        proof["newGenerationSequence1Accepted"] = second;
        proof["newGenerationSequence1ErrorCode"] = secondError;
        var replayZero = tracker.TryCheckAndUpdate("engine", _options.SessionId, Nonce, 0, out var replayError);
        proof["withinGenerationReplayRejected"] = !replayZero;
        proof["withinGenerationReplayErrorCode"] = replayError;

        // (B) old generation nonce - fail closed
        var stale = tracker.TryCheckAndUpdate("engine", _options.SessionId, oldNonce, 999, out var staleError);
        proof["oldGenerationNonce"] = oldNonce[..Math.Min(8, oldNonce.Length)];
        proof["oldGenerationAccepted"] = stale;
        proof["oldGenerationErrorCode"] = staleError;

        // (C) a different session id - fail closed
        var foreign = tracker.TryCheckAndUpdate("engine", foreignSessionId, Nonce, 1000, out var foreignError);
        proof["foreignSessionId"] = foreignSessionId;
        proof["foreignSessionAccepted"] = foreign;
        proof["foreignSessionErrorCode"] = foreignError;

        // Neither stale nor foreign packets may move the high-water mark.
        proof["highWaterUnchangedByStalePackets"] = tracker.HighWater("engine", _options.SessionId, Nonce) == 1;

        // The live session tracker must behave identically for the old nonce.
        var liveStale = EngineSequences.TryCheckAndUpdate("engine", _options.SessionId, oldNonce, 12345, out var liveStaleError);
        proof["liveTrackerOldGenerationAccepted"] = liveStale;
        proof["liveTrackerOldGenerationErrorCode"] = liveStaleError;

        return proof;
    }

    // ---------------------------------------------------------------- helpers

    public long NextHostSequence() => ++HostHeartbeatSequence;

    public string NextRequestId(string prefix) => $"{prefix}-{++HostRequestCounter:0000}";

    private static string NewNonce()
    {
        var bytes = new byte[16];
        System.Security.Cryptography.RandomNumberGenerator.Fill(bytes);
        return Convert.ToHexString(bytes).ToLowerInvariant();
    }

    public void Dispose()
    {
        try
        {
            _pipe?.Dispose();
        }
        catch
        {
            // ignored
        }

        try
        {
            _inbox.CompleteAdding();
        }
        catch
        {
            // ignored
        }
        try
        {
            _pump?.Join(500);
        }
        catch
        {
            // ignored
        }

        try
        {
            if (_child is { HasExited: false })
            {
                _job.Terminate(1);
                _child.WaitForExit(2000);
            }
        }
        catch
        {
            // ignored
        }

        if (_child is not null)
        {
            // Detach the async stdio readers before disposing: Process.Dispose can
            // otherwise block on a still-pending async read.
            try
            {
                _child.CancelOutputRead();
            }
            catch
            {
                // ignored
            }
            try
            {
                _child.CancelErrorRead();
            }
            catch
            {
                // ignored
            }
            _child.Dispose();
        }

        _job.Dispose();
        Mmf.Dispose();
        try
        {
            _inbox.Dispose();
        }
        catch
        {
            // ignored
        }
    }
}
