using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Text.Json.Nodes;
using NteHost.Protocol;

namespace WgcLiveHarness;

internal sealed record WarehouseSourceContext(string RecordKey, JsonObject Target, string ClientMap,
    int Width, int Height, bool SettlementCaptureEligible, bool TargetUsable, long AbsoluteDeadlineNs,
    long MatchGeneration = 0, int WheelDelta = -120, long CaptureScopeEpoch = 0)
{
    // Local to a single scroll command. Never serialized or inherited by later SOURCE requests.
    internal WarehouseScrollAttempt? ScrollAttempt { get; init; }
}

// The lease must never infer NOT_SENT from a failed callback alone: the adapter
// confirms its precise rejection stage or conservatively records API invocation.
internal sealed class WarehouseScrollAttempt
{
    internal bool SendInterfaceInvoked { get; private set; }
    internal bool SendSucceeded { get; private set; }
    internal void MarkSendSucceeded() { if (SendInterfaceInvoked) SendSucceeded = true; }
    internal string? PreSendCurrentGuardRejection { get; private set; }
    internal void RejectCurrentGuardBeforeSend(string reason)
    {
        if (!SendInterfaceInvoked && reason is
            ("CURRENT_GUARD_REJECTED_BEFORE_TARGET_READ" or "CURRENT_GUARD_REJECTED_BEFORE_SEND"))
            PreSendCurrentGuardRejection = reason;
    }
    internal void MarkSendInterfaceInvoked()
    {
        // Mark *before* entering the native/abstracted send: exception means UNKNOWN.
        SendInterfaceInvoked = true;
        PreSendCurrentGuardRejection = null;
    }
    internal bool ConfirmedNotSentByCurrentGuard =>
        !SendInterfaceInvoked && PreSendCurrentGuardRejection is
            ("CURRENT_GUARD_REJECTED_BEFORE_TARGET_READ" or "CURRENT_GUARD_REJECTED_BEFORE_SEND");
}

internal sealed record WarehouseSourceFrame(int Width, int Height, int Stride, byte[] Pixels,
    long SourceTimestampNs, long ReadbackTimestampNs, string CapturedAtUtc, long Sequence,
    string WorkerPixelSha256, long WorkerSequence, CaptureDeliveryProof? DeliveryProof = null,
    DeliveryVisualSummary? VisualSummary = null, long RequestGateNs = 0, long MatchGeneration = 0, long CaptureScopeEpoch = 0);

/// <summary>Host-local, explicitly requested source leases. No business/worker mutations.</summary>
internal sealed class WarehouseEvidenceLease : IDisposable
{
    public const string ControlType = "native_warehouse_evidence_control";
    public const string EventType = "native_warehouse_evidence";
    public const string Schema = "native-warehouse-source.v1";
    public const string SchemaV2 = "native-warehouse-source.v2";
    private readonly string _policy;
    private readonly object _gate = new();
    private DeliveryVisualSummary? _savedSummary;
    private DeliveryVisualSummary? _priorSavedSummary;
    private CaptureDeliveryProof? _lastProof, _savedProof, _priorSavedProof;
    private readonly Func<DeliveryVisualSummary?>? _latestSummary;
    private long _lastReadbackTime, _lastScrollCompletedNs;
    private long _lastContentHintNs;
    private string? _lastContentHintCapture;
    private QpcClockSample? _requestClock;
    private readonly bool _realClock;
    public QpcClockSample? PendingRequestClockSample { get { lock (_gate) return _requestClock; } }
    public const string PngEncoding = "opencv-bgr8-png-bound.v1";
    public const int MaxSources = 16;
    public const int MaxTriggerProbes = 32;
    public const long MinTriggerProbeIntervalNs = 600_000_000;
    public const long MaxRawBytes = 128L * 1024 * 1024;
    public const long MaxPngBytes = 64L * 1024 * 1024;
    private const long SourceWaitNs = 5_000_000_000;
    private const long FreshnessNs = 2_000_000_000;
    private readonly string _workRoot, _root, _triggerRoot, _observation;
    private readonly Action<JsonObject> _emit;
    private readonly Func<long> _clock;
    private readonly Func<WarehouseSourceContext, Func<bool>, bool>? _scrollDown;
    private readonly Action<JsonObject>? _scrollDiagnosticLog;
    private bool _scrollRefusalDiagnosticAttempted;
    private int _transportStopped;
    private int _mappingSuspended, _mappingNeedsContext;
    private long _mappingEpochFloor;
    private WarehouseSourceContext? _context;
    private JsonObject? _open, _request, _source;
    private Signal? _signal;
    private string? _budgetRecord, _budgetMap;
    private int _written, _attempts, _ordinal;
    private long _rawBytes, _requestGate, _requestDeadline, _leaseDeadline, _lastSequence, _lastSourceTime;
    private readonly HashSet<string> _savedHashes = new(StringComparer.Ordinal);
    private readonly HashSet<string> _scrolledSources = new(StringComparer.Ordinal);
    private string? _lastSavedSource, _lastSavedHash;
    private bool _windowScrollAllowed;
    private bool _retainIndependentOriginals;
    private TriggerWatch? _triggerWatch;
    private string? _probeBudgetRecord, _probeBudgetWatchId;
    private long _probeBudgetMatchGeneration = long.MinValue, _probeBudgetDeadlineNs;
    private int _probeBudgetAttempts;

    private sealed class TriggerWatch
    {
        public string Id = string.Empty;
        public string RecordKey = string.Empty;
        public JsonObject Target = new();
        public string ClientMap = string.Empty;
        public long MatchGeneration, DeadlineNs, LastProbeNs, LastProbeSequence;
        public int Attempts, Cancelled;
        public string? PendingProbeId, PendingPath, PendingBmpSha256, PendingPixelSha256;
        public long PendingSequence;
        public FileStream? PendingOwner;
    }

    private sealed record Signal(string Review, int Generation, string Token) { public int Cancelled; }
    public string? LeaseToken { get; private set; }
    public bool IsOpen => Volatile.Read(ref _transportStopped) == 0 && Volatile.Read(ref _mappingSuspended) == 0
        && Volatile.Read(ref _mappingNeedsContext) == 0 && _open is not null
        && _context is { } context && context.CaptureScopeEpoch >= Volatile.Read(ref _mappingEpochFloor)
        && Volatile.Read(ref _signal) is { } signal && Volatile.Read(ref signal.Cancelled) == 0;
    public int WrittenSources => _written;
    public long? PendingRequestGateNs => IsOpen && _request is not null && _source is null ? _requestGate : null;
    public long PendingRequestDeadlineNs => _requestDeadline;
    public object PendingRequestDiagnosticContext => new {
        recordStableKey = _context?.RecordKey, requestId = _request?["commandId"]?.DeepClone(),
        reviewGeneration = _request?["reviewGeneration"]?.DeepClone(),
        observationSessionId = _observation,
    };

    public WarehouseEvidenceLease(string workRoot, string observation, Action<JsonObject> emit, Func<long>? clock = null,
        Func<WarehouseSourceContext, Func<bool>, bool>? scrollDown = null,
        string capturePolicy = CapturePolicy.Strict, Func<DeliveryVisualSummary?>? latestSummary = null,
        Action<JsonObject>? scrollDiagnosticLog = null)
    {
        _workRoot = Path.GetFullPath(workRoot);
        _root = Path.GetFullPath(Path.Combine(workRoot, "warehouse-sources"));
        _triggerRoot = Path.GetFullPath(Path.Combine(workRoot, "warehouse-trigger-probes"));
        _observation = observation; _emit = emit; _clock = clock ?? ProtocolClock.NowNs;
        _realClock = clock is null;
        _scrollDown = scrollDown; _policy = CapturePolicy.Parse(capturePolicy); _latestSummary = latestSummary;
        _scrollDiagnosticLog = scrollDiagnosticLog;
    }

    public void UpdateContext(WarehouseSourceContext context)
    {
        if (context.CaptureScopeEpoch < Volatile.Read(ref _mappingEpochFloor))
            context = context with { TargetUsable = false };
        // Revoke before waiting for in-flight save/message IO.
        var previous = Volatile.Read(ref _context);
        if (previous is not null && (previous.RecordKey != context.RecordKey
            || previous.MatchGeneration != context.MatchGeneration || previous.ClientMap != context.ClientMap
            || !JsonNode.DeepEquals(previous.Target, context.Target)
            || !context.SettlementCaptureEligible || !context.TargetUsable))
            if (Volatile.Read(ref _signal) is { } pending) Interlocked.Exchange(ref pending.Cancelled, 1);
        var trigger = Volatile.Read(ref _triggerWatch);
        if (trigger is not null && (trigger.RecordKey != context.RecordKey
            || trigger.MatchGeneration != context.MatchGeneration || trigger.ClientMap != context.ClientMap
            || !JsonNode.DeepEquals(trigger.Target, context.Target)
            || !context.SettlementCaptureEligible || !context.TargetUsable
            || context.AbsoluteDeadlineNs != trigger.DeadlineNs || _clock() >= trigger.DeadlineNs))
            Interlocked.Exchange(ref trigger.Cancelled, 1);
        lock (_gate)
        {
        if (_open is not null && (_context is null || context.RecordKey != _context.RecordKey || context.MatchGeneration != _context.MatchGeneration
                || context.ClientMap != _context.ClientMap || !JsonNode.DeepEquals(context.Target, _context.Target)
                || !context.SettlementCaptureEligible || !context.TargetUsable)) Close("SOURCE_SCOPE_CHANGED");
        if (_budgetRecord != context.RecordKey)
        {
            _budgetRecord = context.RecordKey; _budgetMap = context.ClientMap;
            _written = _attempts = 0; _rawBytes = _lastSequence = _lastSourceTime = 0; _savedHashes.Clear();
        }
        if (_probeBudgetRecord != context.RecordKey || _probeBudgetMatchGeneration != context.MatchGeneration
            || _probeBudgetDeadlineNs != context.AbsoluteDeadlineNs)
        {
            CancelTriggerWatchLocked("TRIGGER_SCOPE_CHANGED");
            _probeBudgetRecord = context.RecordKey;
            _probeBudgetMatchGeneration = context.MatchGeneration;
            _probeBudgetDeadlineNs = context.AbsoluteDeadlineNs;
            _probeBudgetAttempts = 0;
            _probeBudgetWatchId = null;
        }
        _context = context;
        if (Volatile.Read(ref _mappingSuspended) == 0 && context.TargetUsable
            && context.CaptureScopeEpoch >= Volatile.Read(ref _mappingEpochFloor))
            Interlocked.Exchange(ref _mappingNeedsContext, 0);
        Tick();

        }
    }

    // Reader may invalidate a lease while the Host main loop waits for the worker.
    // It neither saves files nor writes business state and cannot revoke another generation.
    public void SignalClose(JsonObject command)
    {
        var signal = Volatile.Read(ref _signal);
        if (signal is not null && Text(command, "operation") == "CLOSE"
            && Text(command, "observationSessionId") == _observation
            && Text(command, "reviewSessionId") == signal.Review
            && Number(command, "reviewGeneration") == signal.Generation
            && Text(command, "leaseToken") == signal.Token)
            Interlocked.Exchange(ref signal.Cancelled, 1);
    }

    public void SignalStop()
    {
        Interlocked.Exchange(ref _transportStopped, 1);
        if (Volatile.Read(ref _signal) is { } signal) Interlocked.Exchange(ref signal.Cancelled, 1);
        if (Volatile.Read(ref _triggerWatch) is { } watch) Interlocked.Exchange(ref watch.Cancelled, 1);
    }

    // Called by the capture owner: never wait for lease IO/revalidation holding _gate.
    public void SignalMappingPause(long epoch)
    {
        Interlocked.Exchange(ref _mappingSuspended, 1);
        Interlocked.Exchange(ref _mappingNeedsContext, 1);
        Interlocked.Exchange(ref _mappingEpochFloor, epoch);
        if (Volatile.Read(ref _signal) is { } signal) Interlocked.Exchange(ref signal.Cancelled, 1);
        if (Volatile.Read(ref _triggerWatch) is { } watch) Interlocked.Exchange(ref watch.Cancelled, 1);
    }
    public void SignalMappingRecovered() => Interlocked.Exchange(ref _mappingSuspended, 0);

    public void Dispose() => Close("HOST_SOURCE_STOPPED");

    public void Handle(JsonObject command)
    {
        lock (_gate)
        {
        try
        {
            if (Encoding.UTF8.GetByteCount(command.ToJsonString()) > 16 * 1024)
                throw new InvalidOperationException("SOURCE_MESSAGE_TOO_LARGE");
            if (Text(command, "type") != ControlType || Text(command, "schemaVersion") != (_policy == CapturePolicy.Delivery ? SchemaV2 : Schema))
                throw new InvalidOperationException("UNSUPPORTED_SOURCE_SCHEMA");
            if (Text(command, "observationSessionId") != _observation)
                throw new InvalidOperationException("STALE_OBSERVATION_SESSION");
            var op = Required(command, "operation");
            Required(command, "commandId"); Required(command, "nonce");
            if (op == "WATCH_TRIGGER") { ArmTriggerWatch(command); return; }
            if (op == "ACK_TRIGGER_PROBE") { AcknowledgeTriggerProbe(command); return; }
            if (op == "CANCEL_TRIGGER_WATCH") { CancelTriggerWatch(command); return; }
            Required(command, "reviewSessionId");
            if (Number(command, "reviewGeneration") <= 0 || Number(command, "reviewGeneration") > int.MaxValue)
                throw new InvalidOperationException("INVALID_REVIEW_GENERATION");
            if (op == "OPEN") { Open(command); return; }
            if (_open is null)
            {
                if (op == "CLOSE") { Emit(command, "CLOSED", "ALREADY_CLOSED"); return; }
                throw new InvalidOperationException(_written >= MaxSources ? "SOURCE_LIMIT_REACHED" : "NO_ACTIVE_SOURCE_LEASE");
            }
            if (!SameLease(command)) throw new InvalidOperationException("STALE_SOURCE_LEASE");
            if (op == "CLOSE") { Close("MANUAL_SOURCE_CLOSED"); return; }
            if (Volatile.Read(ref _mappingSuspended) != 0 || Volatile.Read(ref _mappingNeedsContext) != 0)
                throw new InvalidOperationException("SOURCE_MAPPING_REVALIDATION_REQUIRED");
            if (_context is { } mappingContext && mappingContext.CaptureScopeEpoch < Volatile.Read(ref _mappingEpochFloor))
                throw new InvalidOperationException("SOURCE_MAPPING_CONTEXT_RETIRED");
            Tick();
            if (!IsOpen) throw new InvalidOperationException("SOURCE_LEASE_EXPIRED");
            if (op == "REQUEST_PAGE") Request(command);
            else if (op == "ACK_SOURCE") Ack(command);
            else if (op == "SCROLL_DOWN") ScrollDown(command);
            else throw new InvalidOperationException("UNKNOWN_SOURCE_OPERATION");
        }
        catch (Exception ex) when (ex is InvalidOperationException or FormatException or OverflowException)
        {
            if (Text(command, "operation") == "SCROLL_DOWN")
                LogScroll(command, "lease-command-rejected", new JsonObject {
                    ["reason"] = ex.Message, ["sendInterfaceInvoked"] = null,
                    ["meaning"] = "see adapter stages; an exception here alone does not establish whether input was sent" });
            Emit(command, "REJECTED", ex.Message);
        }

        }
    }

    private void Open(JsonObject command)
    {
        if (Volatile.Read(ref _transportStopped) != 0) throw new InvalidOperationException("SOURCE_TRANSPORT_CLOSED");
        if (IsOpen) throw new InvalidOperationException("SOURCE_LEASE_ALREADY_OPEN");
        var c = _context ?? throw new InvalidOperationException("SOURCE_CONTEXT_UNAVAILABLE");
        if (!c.TargetUsable || !c.SettlementCaptureEligible) throw new InvalidOperationException("SETTLEMENT_NOT_AVAILABLE_OR_TARGET_UNUSABLE");
        if (!ValidGeometry(c.Width, c.Height)) throw new InvalidOperationException("FIXED_V1_GEOMETRY_REJECTED");
        if (Required(command, "recordStableKey") != c.RecordKey
            || !JsonNode.DeepEquals(command["expectedTargetInstance"], c.Target)
            || (_policy == CapturePolicy.Delivery && Number(command, "matchGeneration") != c.MatchGeneration))
            throw new InvalidOperationException("SOURCE_SCOPE_CHANGED");
        if (_clock() >= c.AbsoluteDeadlineNs) throw new InvalidOperationException("ABSOLUTE_SETTLEMENT_BUDGET_EXPIRED");
        if (_written >= MaxSources || _rawBytes >= MaxRawBytes || _attempts >= 32 || c.ClientMap != _budgetMap)
            throw new InvalidOperationException("SOURCE_LIMIT_REACHED");
        CancelTriggerWatchLocked("SOURCE_OPENED");
        _open = (JsonObject)command.DeepClone(); _request = _source = null; _ordinal = 0;
        _windowScrollAllowed = command["allowWindowScroll"] is JsonValue flag
            && flag.TryGetValue<bool>(out var allow) && allow;
        _retainIndependentOriginals = command["retainIndependentOriginals"] is JsonValue retain
            && retain.TryGetValue<bool>(out var keep) && keep;
        // Retaining independent equal originals is also necessary for visible
        // support during collection. Input still requires its separate arming flag.
        if (_retainIndependentOriginals && _policy != CapturePolicy.Delivery)
        { _open = null; throw new InvalidOperationException("EVIDENCE_ONLY_SOURCE_REQUIRED"); }
        _lastSavedSource = _lastSavedHash = null; _scrolledSources.Clear();
        _lastProof = _savedProof = _priorSavedProof = null; _savedSummary = _priorSavedSummary = null;
        LeaseToken = Guid.NewGuid().ToString("N");
        Volatile.Write(ref _signal, new Signal(Required(command, "reviewSessionId"), (int)Number(command, "reviewGeneration"), LeaseToken));
        _leaseDeadline = Math.Min(c.AbsoluteDeadlineNs, checked(_clock() + 70_000_000_000));
        Emit(command, "OPENED", null, new JsonObject {
            ["deadlineNs"] = _leaseDeadline, ["maxWidth"] = ProtocolConstants.MaxFrameWidth,
            ["maxHeight"] = ProtocolConstants.MaxFrameHeight, ["remainingSourcePages"] = MaxSources - _written,
            ["remainingRawBytes"] = MaxRawBytes - _rawBytes, ["maxPngBytes"] = MaxPngBytes,
            ["pngEncoding"] = PngEncoding, ["clientMap"] = c.ClientMap,
            ["windowScrollSupported"] = _windowScrollAllowed && _scrollDown is not null,
            ["retainIndependentOriginals"] = _retainIndependentOriginals,
            ["clientWidth"] = c.Width, ["clientHeight"] = c.Height });
    }

    private void Request(JsonObject command)
    {
        var c = _context!;
        if (_request is not null || _source is not null) throw new InvalidOperationException("SOURCE_REQUEST_PENDING");
        var ordinal = Number(command, "requestOrdinal");
        if (ordinal <= _ordinal || ordinal > int.MaxValue) throw new InvalidOperationException("STALE_SOURCE_REQUEST");
        if (++_attempts > 32) { Close("SOURCE_LIMIT_REACHED"); throw new InvalidOperationException("SOURCE_LIMIT_REACHED"); }
        _ordinal = (int)ordinal;
        var pages = Number(command, "remainingPages"); var pngBytes = Number(command, "remainingPngBytes");
        if (pages <= 0 || pages > MaxSources || _written >= MaxSources
            || _rawBytes + 54L + 4L * c.Width * c.Height > MaxRawBytes)
        { Close("SOURCE_LIMIT_REACHED"); throw new InvalidOperationException("SOURCE_LIMIT_REACHED"); }
        if (Text(command, "pngEncoding") != PngEncoding || pngBytes > MaxPngBytes || pngBytes < PngUpperBound(c.Width, c.Height))
            throw new InvalidOperationException("PNG_BUDGET_INSUFFICIENT");
        _requestClock = _realClock ? QpcClockSample.Read() : null;
        _requestGate = _requestClock?.Nanoseconds ?? _clock();
        if (_policy == CapturePolicy.Delivery && _requestGate < _lastScrollCompletedNs) throw new InvalidOperationException("SOURCE_BEFORE_SCROLL_COMPLETED");
        _requestDeadline = Math.Min(_leaseDeadline, checked(_requestGate + SourceWaitNs));
        _request = (JsonObject)command.DeepClone();
        Emit(command, "RESULT", "SOURCE_REQUESTED");
    }

    // OpenCV's current BGR8 PNG contains 3 bytes/pixel plus row filter and bounded zlib/chunk overhead.
    // This deliberately conservative bound is checked upstream; accepted PNG bytes remain exact downstream.
    public static long PngUpperBound(int width, int height) => checked(4L * width * height + 65536);

    public void Tick()
    {
        lock (_gate)
        {
        if (_triggerWatch is { } watch)
        {
            if (Volatile.Read(ref watch.Cancelled) != 0) CancelTriggerWatchLocked("TRIGGER_SCOPE_REVOKED");
            else if (_clock() >= watch.DeadlineNs) CancelTriggerWatchLocked("ABSOLUTE_SETTLEMENT_BUDGET_EXPIRED");
        }
        if (_open is null) return;
        if (!IsOpen) { Close("MANUAL_SOURCE_CANCELLED"); return; }
        if (_clock() >= _leaseDeadline) { Close("ABSOLUTE_SETTLEMENT_BUDGET_EXPIRED"); return; }
        if ((_request is not null && _clock() >= _requestDeadline)
            || (_source is not null && _clock() >= _requestDeadline))
        { var failed = _request ?? _open; _request = _source = null; Emit(failed, "REJECTED", "SOURCE_REQUEST_TIMEOUT"); }
        PublishContentHint();
        }
    }

    private void PublishContentHint()
    {
        // Observe the already-running capture; no explicit acquisition or saved SOURCE.
        // One overwriteable ROI slot only. Hints can schedule requests, never authorize input.
        if (_policy != CapturePolicy.Delivery || _context is not { } c || !_windowScrollAllowed
            || !c.TargetUsable || !c.SettlementCaptureEligible || _request is not null || _source is not null) return;
        var summary = _latestSummary?.Invoke(); var now = _clock();
        if (summary is null || !summary.ActionQualified || summary.ScrollContentBgr is not { } bgr
            || !summary.CaptureId.StartsWith(_observation + "/", StringComparison.Ordinal)
            || summary.ReadbackNs > now || now - summary.ReadbackNs > FreshnessNs
            || now - _lastContentHintNs < MinTriggerProbeIntervalNs || summary.CaptureId == _lastContentHintCapture) return;
        _lastContentHintNs = now; _lastContentHintCapture = summary.CaptureId;
        var box = DeliveryVisualSummary.ScrollContentBox(c.Width, c.Height);
        var width = box.Right - box.Left; var height = box.Bottom - box.Top;
        if (bgr.Length != width * height * 3) return;
        var pixels = new byte[width * height * 4];
        for (var i = 0; i < width * height; i++) {
            pixels[i*4] = bgr[i*3]; pixels[i*4+1] = bgr[i*3+1]; pixels[i*4+2] = bgr[i*3+2]; pixels[i*4+3] = 255;
        }
        var path = Path.Combine(_root, "content-observation.bmp"); var temp = path + ".tmp";
        var publicationStage = "create-directory";
        try {
            Directory.CreateDirectory(_root); TryDelete(temp);
            publicationStage = "write-temporary";
            WriteNewBmp(temp, new WarehouseSourceFrame(width, height, width*4, pixels, 0, summary.ReadbackNs, "", 0, "", 0));
            publicationStage = "replace-slot";
            File.Move(temp, path, overwrite:true);
            publicationStage = "verify-and-emit";
            Emit(_open!, "CONTENT_HINT", "OBSERVATION_ONLY", new JsonObject {
                ["path"] = path, ["sha256"] = HashFile(path), ["width"] = width, ["height"] = height,
                ["clientMap"] = c.ClientMap, ["captureId"] = summary.CaptureId, ["readbackNs"] = summary.ReadbackNs,
                ["sourceAuthority"] = false, ["formalFactsQualified"] = false });
        } catch (Exception ex) when (ex is IOException or UnauthorizedAccessException) {
            // A queued Python reader can hold this volatile slot without delete
            // sharing. Windows may report its replacement as access denied.
            // Dropping a scheduling hint never grants a SOURCE or input action;
            // the next independent summary may retry under the same deadline.
            TryDelete(temp);
            Emit(_open!, "CONTENT_HINT_SKIPPED", "CONTENT_HINT_FILE_UNAVAILABLE", new JsonObject {
                ["publicationStage"] = publicationStage, ["path"] = path,
                ["exceptionType"] = ex.GetType().Name, ["error"] = ex.Message,
                ["sourceAuthority"] = false, ["formalFactsQualified"] = false });
        }
    }

    public bool PublishTriggerProbe(WarehouseSourceFrame frame, Func<bool> revalidateTarget)
    {
        lock (_gate)
        {
            Tick();
            var watch = _triggerWatch;
            var context = _context;
            if (watch is null || context is null || Volatile.Read(ref watch.Cancelled) != 0
                || _open is not null || watch.PendingProbeId is not null) return false;
            var now = _clock();
            if (now >= watch.DeadlineNs)
            { CancelTriggerWatchLocked("ABSOLUTE_SETTLEMENT_BUDGET_EXPIRED"); return false; }
            if (_probeBudgetAttempts >= MaxTriggerProbes)
            { CancelTriggerWatchLocked("TRIGGER_PROBE_LIMIT_REACHED"); return false; }
            if (watch.LastProbeNs != 0 && now - watch.LastProbeNs < MinTriggerProbeIntervalNs) return false;
            if (!ContextMatchesWatch(context, watch) || !revalidateTarget())
            { CancelTriggerWatchLocked("TRIGGER_SCOPE_CHANGED"); return false; }
            if (!ValidGeometry(frame.Width, frame.Height) || frame.Width != context.Width || frame.Height != context.Height
                || frame.Stride != checked(frame.Width * 4) || frame.Pixels.Length != checked(frame.Stride * frame.Height)
                || frame.Sequence <= watch.LastProbeSequence || frame.SourceTimestampNs <= 0 || frame.ReadbackTimestampNs < frame.SourceTimestampNs
                || now < frame.ReadbackTimestampNs || now - frame.ReadbackTimestampNs > 2_000_000_000)
            { CancelTriggerWatchLocked("TRIGGER_PROBE_FRAME_REJECTED"); return false; }

            // Every materialized probe consumes one finite attempt, even if file publication fails.
            watch.Attempts++;
            _probeBudgetAttempts++;
            watch.LastProbeNs = now;
            watch.LastProbeSequence = frame.Sequence;
            var probeId = Guid.NewGuid().ToString("N");
            var directory = Path.GetFullPath(Path.Combine(_triggerRoot, watch.Id));
            if (!directory.StartsWith(_triggerRoot + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
            { CancelTriggerWatchLocked("TRIGGER_PROBE_PATH_REJECTED"); return false; }
            var tempPath = Path.Combine(directory, "." + probeId + ".tmp");
            var finalPath = Path.Combine(directory, probeId + ".bmp");
            try
            {
                Directory.CreateDirectory(directory);
                WriteNewBmp(tempPath, frame);
                var bmpHash = HashFile(tempPath);
                var pixelHash = Convert.ToHexString(SHA256.HashData(frame.Pixels)).ToLowerInvariant();
                File.Move(tempPath, finalPath); // same-volume, unique destination; never replaces another frame
                var owner = new FileStream(finalPath, FileMode.Open, FileAccess.Read,
                    FileShare.Read, 1, FileOptions.SequentialScan);
                watch.PendingProbeId = probeId;
                watch.PendingPath = finalPath;
                watch.PendingBmpSha256 = bmpHash;
                watch.PendingPixelSha256 = pixelHash;
                watch.PendingSequence = frame.Sequence;
                watch.PendingOwner = owner;
                if (!ContextMatchesWatch(_context, watch) || !revalidateTarget()
                    || _clock() < frame.ReadbackTimestampNs || _clock() - frame.ReadbackTimestampNs > 2_000_000_000
                    || Volatile.Read(ref watch.Cancelled) != 0)
                {
                    CancelTriggerWatchLocked("TRIGGER_SCOPE_CHANGED_DURING_PUBLISH");
                    return false;
                }
                EmitTrigger(watch, "TRIGGER_PROBE", null, new JsonObject {
                    ["probeId"] = probeId, ["probeOrdinal"] = watch.Attempts,
                    ["probeLimit"] = MaxTriggerProbes, ["minimumIntervalMs"] = MinTriggerProbeIntervalNs / 1_000_000,
                    ["relativePath"] = Path.GetRelativePath(_workRoot, finalPath).Replace('\\', '/'),
                    ["bmpSha256"] = bmpHash, ["pixelSha256"] = pixelHash,
                    ["frameSequence"] = frame.Sequence, ["sourceTimestampNs"] = frame.SourceTimestampNs,
                    ["readbackTimestampNs"] = frame.ReadbackTimestampNs,
                    ["width"] = frame.Width, ["height"] = frame.Height, ["stride"] = frame.Stride,
                    ["capturePolicy"] = _policy,
                    ["deliveryProof"] = frame.DeliveryProof?.ToJson(),
                    ["sourcePagesWritten"] = _written, ["sourceRequestAttempts"] = _attempts,
                    ["probeAttempts"] = watch.Attempts, ["remainingProbeAttempts"] = MaxTriggerProbes - watch.Attempts,
                    ["deadlineNs"] = watch.DeadlineNs,
                });
                return true;
            }
            catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or InvalidOperationException)
            {
                TryDelete(tempPath);
                TryDelete(finalPath);
                CancelTriggerWatchLocked("TRIGGER_PROBE_PUBLISH_FAILED:" + ex.GetType().Name);
                return false;
            }
        }
    }

    private void ArmTriggerWatch(JsonObject command)
    {
        var id = Required(command, "watchId");
        if (!Regex.IsMatch(id, "^[0-9a-f]{32}$")) throw new InvalidOperationException("INVALID_TRIGGER_WATCH_ID");
        var context = _context ?? throw new InvalidOperationException("SOURCE_CONTEXT_UNAVAILABLE");
        if (_transportStopped != 0 || _open is not null || !context.TargetUsable || !context.SettlementCaptureEligible
            || _clock() >= context.AbsoluteDeadlineNs) throw new InvalidOperationException("SETTLEMENT_NOT_AVAILABLE_OR_TARGET_UNUSABLE");
        if (Text(command, "recordStableKey") != context.RecordKey
            || !JsonNode.DeepEquals(command["expectedTargetInstance"], context.Target)
            || Text(command, "clientMap") != context.ClientMap
            || Number(command, "matchGeneration") != context.MatchGeneration)
            throw new InvalidOperationException("TRIGGER_SCOPE_CHANGED");
        if (Number(command, "maxProbes") != MaxTriggerProbes
            || Number(command, "minimumIntervalNs") != MinTriggerProbeIntervalNs)
            throw new InvalidOperationException("TRIGGER_PROBE_BUDGET_MISMATCH");
        if (_triggerWatch is { } existing)
        {
            if (existing.Id == id) { EmitTrigger(existing, "TRIGGER_WATCH_ARMED", "IDEMPOTENT_REPLAY", null); return; }
            throw new InvalidOperationException("TRIGGER_WATCH_ALREADY_ACTIVE");
        }
        if (_probeBudgetWatchId is not null || _probeBudgetAttempts >= MaxTriggerProbes)
            throw new InvalidOperationException("TRIGGER_PROBE_BUDGET_EXHAUSTED");
        _probeBudgetWatchId = id;
        _triggerWatch = new TriggerWatch { Id = id, RecordKey = context.RecordKey,
            Target = (JsonObject)context.Target.DeepClone(), ClientMap = context.ClientMap,
            MatchGeneration = context.MatchGeneration, DeadlineNs = context.AbsoluteDeadlineNs };
        EmitTrigger(_triggerWatch, "TRIGGER_WATCH_ARMED", null, null);
    }

    private void AcknowledgeTriggerProbe(JsonObject command)
    {
        var watch = _triggerWatch;
        var context = _context;
        if (watch is null || context is null || !TriggerCommandMatches(command, watch, context)
            || Text(command, "probeId") != watch.PendingProbeId)
            throw new InvalidOperationException("STALE_TRIGGER_PROBE_ACK");
        var probeId = watch.PendingProbeId;
        ReleasePendingProbe(watch);
        var result = Text(command, "result") ?? "REJECTED";
        var reason = Text(command, "reason") ?? string.Empty;
        EmitTrigger(watch, "TRIGGER_PROBE_ACKED", reason.Length == 0 ? result : reason,
            new JsonObject { ["probeId"] = probeId, ["result"] = result,
                ["reasonCodes"] = command["reasonCodes"]?.DeepClone(),
                ["probeAttempts"] = watch.Attempts, ["probeLimit"] = MaxTriggerProbes,
                ["sourcePagesWritten"] = _written, ["sourceRequestAttempts"] = _attempts });
        if (result == "ELIGIBLE") CancelTriggerWatchLocked("TRIGGER_QUALIFIED_SOURCE_START_REQUESTED");
        else if (watch.Attempts >= MaxTriggerProbes) CancelTriggerWatchLocked("TRIGGER_PROBE_LIMIT_REACHED");
    }

    private void CancelTriggerWatch(JsonObject command)
    {
        var watch = _triggerWatch;
        var context = _context;
        if (watch is null) return;
        if (context is null || !TriggerCommandMatches(command, watch, context))
            throw new InvalidOperationException("STALE_TRIGGER_WATCH_CANCEL");
        CancelTriggerWatchLocked(Text(command, "reason") ?? "TRIGGER_WATCH_CANCELLED");
    }

    private bool TriggerCommandMatches(JsonObject command, TriggerWatch watch, WarehouseSourceContext context) =>
        Text(command, "watchId") == watch.Id && Text(command, "observationSessionId") == _observation
        && Text(command, "recordStableKey") == watch.RecordKey && context.RecordKey == watch.RecordKey
        && Number(command, "matchGeneration") == watch.MatchGeneration && context.MatchGeneration == watch.MatchGeneration
        && JsonNode.DeepEquals(command["expectedTargetInstance"], watch.Target)
        && JsonNode.DeepEquals(context.Target, watch.Target) && Text(command, "clientMap") == watch.ClientMap
        && context.ClientMap == watch.ClientMap;

    private static bool ContextMatchesWatch(WarehouseSourceContext? context, TriggerWatch watch) => context is not null
        && context.RecordKey == watch.RecordKey && context.MatchGeneration == watch.MatchGeneration
        && context.ClientMap == watch.ClientMap && JsonNode.DeepEquals(context.Target, watch.Target)
        && context.SettlementCaptureEligible && context.TargetUsable
        && context.AbsoluteDeadlineNs == watch.DeadlineNs;

    private void CancelTriggerWatchLocked(string reason)
    {
        var watch = _triggerWatch;
        if (watch is null) return;
        Interlocked.Exchange(ref watch.Cancelled, 1);
        ReleasePendingProbe(watch);
        EmitTrigger(watch, "TRIGGER_WATCH_ENDED", reason,
            new JsonObject { ["probeAttempts"] = watch.Attempts, ["probeLimit"] = MaxTriggerProbes,
                ["sourcePagesWritten"] = _written, ["sourceRequestAttempts"] = _attempts });
        _triggerWatch = null;
    }

    private static void ReleasePendingProbe(TriggerWatch watch)
    {
        var owner = watch.PendingOwner;
        var path = watch.PendingPath;
        watch.PendingOwner = null;
        try { owner?.Dispose(); } catch (IOException) { }
        if (path is not null) TryDelete(path);
        watch.PendingProbeId = watch.PendingPath = watch.PendingBmpSha256 = watch.PendingPixelSha256 = null;
        watch.PendingSequence = 0;
    }

    private void EmitTrigger(TriggerWatch watch, string evt, string? reason, JsonObject? details)
    {
        details ??= new JsonObject();
        details["probeAttempts"] ??= watch.Attempts;
        details["probeLimit"] ??= MaxTriggerProbes;
        details["sourcePagesWritten"] ??= _written;
        details["sourceRequestAttempts"] ??= _attempts;
        _emit(new JsonObject { ["type"] = EventType,
            ["schemaVersion"] = _policy == CapturePolicy.Delivery ? SchemaV2 : Schema,
            ["event"] = evt, ["watchId"] = watch.Id, ["capturePolicy"] = _policy,
            ["scene"] = "UNCLASSIFIED_CURRENT_PROBE",
            ["observationSessionId"] = _observation, ["sourceKind"] = "native_wgc",
            ["inputActions"] = false, ["formalHistoryWriter"] = false,
            ["recordStableKey"] = watch.RecordKey, ["matchGeneration"] = watch.MatchGeneration,
            ["targetInstance"] = watch.Target.DeepClone(), ["clientMap"] = watch.ClientMap,
            ["deadlineNs"] = watch.DeadlineNs, ["reason"] = reason, ["details"] = details.DeepClone() });
    }

    private static string HashFile(string path)
    {
        using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
    }

    private static void TryDelete(string path)
    {
        try { if (File.Exists(path)) File.Delete(path); } catch (IOException) { } catch (UnauthorizedAccessException) { }
    }

    public bool TryPublish(WarehouseSourceFrame frame, Func<bool> revalidateTarget)
    {
        lock (_gate)
        {
        Tick();
        var request = _request; var c = _context;
        if (request is null || c is null || !IsOpen || _source is not null) return false;
        if (frame.CaptureScopeEpoch < Volatile.Read(ref _mappingEpochFloor)) return false;
        if (!revalidateTarget()) { Close("SOURCE_TARGET_CHANGED"); return false; }
        var now = _clock();
        if (_policy == CapturePolicy.Delivery)
        {
            if (frame.RequestGateNs != _requestGate || frame.MatchGeneration != c.MatchGeneration) return false;
            if (frame.DeliveryProof is not { } proof || proof.ObservationSessionId != _observation
                || proof.AcquisitionSequence != frame.Sequence || proof.RequestNs != _requestGate || proof.SourceNs != frame.SourceTimestampNs
                || proof.ReadbackCompletedNs != frame.ReadbackTimestampNs || proof.Rejection(now) is not null
                || !proof.SourceMarkerProgress || frame.Sequence <= _lastSequence)
            { Close("SOURCE_DELIVERY_PROOF_REJECTED"); return false; }
            _lastProof = proof;
        }
        else if (frame.SourceTimestampNs <= _requestGate || frame.SourceTimestampNs <= _lastSourceTime
            || frame.SourceTimestampNs > now || now - frame.SourceTimestampNs > FreshnessNs
            || frame.Sequence <= _lastSequence) return false;
        if (frame.Width != c.Width || frame.Height != c.Height || !ValidGeometry(frame.Width, frame.Height)
            || frame.Stride != frame.Width * 4 || frame.Pixels.LongLength != 4L * frame.Width * frame.Height)
        { Close("SOURCE_GEOMETRY_CHANGED"); return false; }
        var pixelHash = Convert.ToHexString(SHA256.HashData(frame.Pixels)).ToLowerInvariant();
        if (_policy != CapturePolicy.Delivery && (frame.Sequence != frame.WorkerSequence || !string.Equals(pixelHash, frame.WorkerPixelSha256, StringComparison.Ordinal)))
        { _request = null; Emit(request, "REJECTED", "WORKER_SOURCE_HASH_MISMATCH"); return false; }
        // Hashing/target checks may race with a reader cancellation. Recheck at file admission.
        Tick();
        if (!IsOpen || _request is null) return false;
        if (!_retainIndependentOriginals && _savedHashes.Contains(pixelHash))
        {
            if (!revalidateTarget() || !IsOpen) { Close("SOURCE_TARGET_CHANGED"); return false; }
            _request = null;
            Emit(request, "RESULT", "DUPLICATE_PAGE", new JsonObject {
                ["sourceTimestampNs"] = frame.SourceTimestampNs, ["requestGateNs"] = _requestGate,
                ["pixelSha256"] = pixelHash, ["frameSequence"] = frame.Sequence, ["clientMap"] = c.ClientMap,
                ["deliveryProof"] = frame.DeliveryProof?.ToJson(), ["readbackTimestampNs"] = frame.ReadbackTimestampNs });
            _lastSequence = frame.Sequence; _lastReadbackTime = frame.ReadbackTimestampNs;
            return false;
        }
        var sourceId = Guid.NewGuid().ToString("N");
        var path = Path.Combine(_root, sourceId + ".bmp");
        // Charge potential files before IO, including failed/partially written originals; never silently delete.
        _written++; _rawBytes += 54L + frame.Pixels.LongLength;
        _lastSequence = frame.Sequence; _lastSourceTime = frame.SourceTimestampNs; _lastReadbackTime = frame.ReadbackTimestampNs;
        _priorSavedSummary = _savedSummary; _savedSummary = frame.VisualSummary;
        _priorSavedProof = _savedProof; _savedProof = frame.DeliveryProof;
        try
        {
            Directory.CreateDirectory(_root);
            WriteNewBmp(path, frame);
            using var stream = File.OpenRead(path);
            if (stream.Length != 54L + frame.Pixels.LongLength) throw new IOException("SOURCE_SIZE_CHANGED");
            var bmpHash = Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
            if (!revalidateTarget() || !IsOpen || _clock() >= _requestDeadline)
            { Close("SOURCE_SCOPE_CHANGED_DURING_SAVE"); return false; }
            _source = new JsonObject { ["sourceLeaseId"] = sourceId, ["path"] = path,
                ["width"] = frame.Width, ["height"] = frame.Height, ["stride"] = frame.Stride,
                ["sourceTimestampNs"] = frame.SourceTimestampNs, ["requestGateNs"] = _requestGate,
                ["readbackTimestampNs"] = frame.ReadbackTimestampNs, ["capturedAtUtc"] = frame.CapturedAtUtc,
                ["frameSequence"] = frame.Sequence, ["pixelSha256"] = pixelHash, ["bmpSha256"] = bmpHash,
                ["workerFrameSequence"] = frame.WorkerSequence,
                ["byteCount"] = stream.Length, ["clientMap"] = c.ClientMap };
            if (_policy == CapturePolicy.Delivery)
            {
                _source.Remove("workerFrameSequence");
                _source["capturePolicy"] = _policy; _source["deliveryProof"] = frame.DeliveryProof!.ToJson();
                _source["matchGeneration"] = c.MatchGeneration;
                _source["savedAtNs"] = _clock();
                _source["formalFactsQualified"] = false;
            }
            Emit(request, "SOURCE", null, null, _source);
            return true;
        }
        catch (Exception ex) when (ex is IOException or UnauthorizedAccessException or OverflowException)
        {
            _request = _source = null; Emit(request, "REJECTED", "SOURCE_WRITE_FAILED");
            if (_written >= MaxSources || _rawBytes >= MaxRawBytes) Close("SOURCE_LIMIT_REACHED");
            return false;
        }

        }
    }

    private void Ack(JsonObject command)
    {
        if (_source is null || _request is null || Text(command, "nonce") != Text(_request, "nonce")
            || Number(command, "requestOrdinal") != _ordinal
            || Text(command, "sourceLeaseId") != Text(_source, "sourceLeaseId")
            || Text(command, "bmpSha256") != Text(_source, "bmpSha256")
            || Text(command, "pixelSha256") != Text(_source, "pixelSha256"))
            throw new InvalidOperationException("STALE_SOURCE_ACK");
        var result = Required(command, "result");
        if (result is not ("SAVED" or "DUPLICATE" or "REJECTED")) throw new InvalidOperationException("INVALID_SOURCE_ACK");
        if (result is "SAVED" or "DUPLICATE") _savedHashes.Add(Required(_source, "pixelSha256"));
        if (result == "SAVED")
        { _lastSavedSource = Required(_source, "sourceLeaseId"); _lastSavedHash = Required(_source, "pixelSha256"); }
        _request = _source = null; Emit(command, "RESULT", result);
        if (_written >= MaxSources || _rawBytes >= MaxRawBytes) Close("SOURCE_LIMIT_REACHED");
    }

    private void LogScroll(JsonObject command, string stage, JsonObject details)
    {
        if (_scrollDiagnosticLog is null) return;
        details["stage"] = stage; details["commandId"] = command["commandId"]?.DeepClone();
        details["recordStableKey"] = _context?.RecordKey;
        details["matchGeneration"] = _context?.MatchGeneration;
        details["observationSessionId"] = _observation;
        try { _scrollDiagnosticLog(details); } catch { } // logging never grants authority
    }

    private void PreserveScrollRefusal(JsonObject command, DeliveryVisualSummary? latest, JsonObject details)
    {
        if (_scrollRefusalDiagnosticAttempted) return;
        _scrollRefusalDiagnosticAttempted = true; // first refusal only; no IO retry loop
        var meta = (JsonObject)details.DeepClone();
        meta["schemaVersion"] = "scroll-refusal-diagnostic.v1";
        meta["sourceAuthority"] = false; meta["formalFactsQualified"] = false;
        meta["diagnosticOnly"] = true; meta["inputActions"] = false;
        meta["clientMap"] = _context?.ClientMap;
        meta["targetInstance"] = _context?.Target.DeepClone();
        var frame = latest?.DiagnosticFrame;
        try
        {
            // Use the exact immutable payload frozen with the guard summary,
            // never a later capture or a new WGC/SOURCE request.
            if (latest is null || frame is null || frame.DeliveryProof?.CaptureId != latest.CaptureId
                || frame.CaptureTimestampNs != latest.ReadbackNs || frame.Stride != frame.Width * 4
                || frame.Pixels.Length != frame.Stride * frame.Height)
                throw new InvalidOperationException("GUARD_DIAGNOSTIC_FRAME_UNAVAILABLE");
            var dir = Path.Combine(_workRoot, "warehouse-scroll-refusal");
            Directory.CreateDirectory(dir);
            var path = Path.Combine(dir, "first-refusal.bmp");
            WriteNewBmp(path, new(frame.Width, frame.Height, frame.Stride, frame.Pixels,
                frame.SourceTimestampNs, frame.CaptureTimestampNs, frame.CapturedAtUtc, frame.AcquisitionSequence,
                "", 0));
            meta["framePath"] = path;
            meta["captureId"] = frame.DeliveryProof.CaptureId;
            meta["sourceTimestampNs"] = frame.SourceTimestampNs;
            meta["readbackTimestampNs"] = frame.CaptureTimestampNs;
            meta["capturedAtUtc"] = frame.CapturedAtUtc;
            meta["width"] = frame.Width; meta["height"] = frame.Height; meta["stride"] = frame.Stride;
            meta["pixelSha256"] = Convert.ToHexString(SHA256.HashData(frame.Pixels)).ToLowerInvariant();
            meta["bmpSha256"] = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))).ToLowerInvariant();
            meta["deliveryProof"] = frame.DeliveryProof.ToJson();
            meta["metadataPath"] = Path.Combine(dir, "first-refusal.json");
            meta["saved"] = true;
            meta["commandId"] = command["commandId"]?.DeepClone();
            meta["recordStableKey"] = _context?.RecordKey; meta["matchGeneration"] = _context?.MatchGeneration;
            meta["observationSessionId"] = _observation;
            File.WriteAllText(meta["metadataPath"]!.GetValue<string>(), meta.ToJsonString());
        }
        catch (Exception ex) { meta["saved"] = false; meta["error"] = ex.Message; meta["exceptionType"] = ex.GetType().Name; }
        // A diagnostic write failure cannot close/renew a SOURCE lease or grant input.
        details["refusalDiagnostic"] = meta.DeepClone();
        LogScroll(command, "refusal-evidence", meta);
    }

    private bool DeliveryScrollCurrent(JsonObject command, long now, JsonObject checks, JsonObject details,
        DeliveryVisualSummary? latest)
    {
        var saved = _savedSummary;
        checks["lastProofPresent"] = _lastProof is not null;
        checks["savedProofPresent"] = _savedProof is not null;
        checks["latestSummaryPresent"] = latest is not null;
        checks["savedSummaryPresent"] = saved is not null;
        if (_lastProof is null || _savedProof is null || latest is null || saved is null) return false;
        var baseProof = Text(command, "savedCaptureId") == _savedProof.CaptureId ? _savedProof : _priorSavedProof;
        checks["baseProofPresent"] = baseProof is not null;
        if (baseProof is null) return false;
        var baseSummary = baseProof == _savedProof ? _savedSummary : _priorSavedSummary;
        checks["baseSummaryPresent"] = baseSummary is not null && baseSummary.CaptureId == baseProof.CaptureId;
        checks["savedCaptureIdMatches"] = Text(command, "savedCaptureId") == baseProof.CaptureId;
        checks["differentCaptureIds"] = _lastProof.CaptureId != baseProof.CaptureId;
        checks["sourceMarkerProgress"] = _lastProof.SourceMarkerProgress;
        checks["independentRequestInterval"] = _lastProof.RequestNs >= baseProof.ReadbackCompletedNs + 250_000_000;
        checks["basePoolEpochMatches"] = _lastProof.PoolEpoch == baseProof.PoolEpoch;
        checks["stableCaptureIdMatches"] = Text(command, "stableCaptureId") == _lastProof.CaptureId;
        var rejection = _lastProof.Rejection(now);
        checks["deliveryProofQualified"] = rejection is null;
        checks["latestReadbackAfterSupport"] = latest.ReadbackNs >= _lastProof.ReadbackCompletedNs;
        checks["latestActionQualified"] = latest.ActionQualified;
        checks["latestPoolEpochMatches"] = latest.Epoch == _lastProof.PoolEpoch;
        checks["latestReadbackNotFuture"] = now >= latest.ReadbackNs;
        checks["latestReadbackWithinDeadline"] = now - latest.ReadbackNs <= FreshnessNs;
        checks["savedSummaryCaptureIdMatches"] = saved.CaptureId == _lastProof.CaptureId;
        checks["latestSessionMatches"] = latest.CaptureId.StartsWith(_observation + "/", StringComparison.Ordinal);
        checks["sceneShapeSupported"] = latest.SceneSupportedBy(saved)
            && baseSummary is not null && latest.SceneSupportedBy(baseSummary);
        checks["scrollContentRoiPresent"] = !string.IsNullOrEmpty(latest.ScrollContentRoiSha256)
            && !string.IsNullOrEmpty(saved.ScrollContentRoiSha256);
        checks["scrollContentQuantizationSupported"] = latest.ContentSupportedBy(saved)
            && baseSummary is not null && latest.ContentSupportedBy(baseSummary);
        details["deliveryProofRejection"] = rejection;
        details["baseCaptureId"] = baseProof.CaptureId; details["supportCaptureId"] = _lastProof.CaptureId;
        details["latestCaptureId"] = latest.CaptureId; details["latestReadbackNs"] = latest.ReadbackNs;
        details["supportReadbackNs"] = _lastProof.ReadbackCompletedNs;
        details["latestSceneHash"] = latest.SceneRoiSha256; details["savedSceneHash"] = saved.SceneRoiSha256;
        details["latestWarehouseHash"] = latest.WarehouseRoiSha256; details["savedWarehouseHash"] = saved.WarehouseRoiSha256;
        details["latestScrollContentHash"] = latest.ScrollContentRoiSha256; details["savedScrollContentHash"] = saved.ScrollContentRoiSha256;
        return checks.All(pair => pair.Value!.GetValue<bool>());
    }

    public (long Gate, long Deadline, long Match, string Token)? RequestSnapshot()
    {
        lock (_gate) return PendingRequestGateNs is long gate && _context is { } c
            ? (gate, _requestDeadline, c.MatchGeneration, LeaseToken!) : null;
    }
    public bool RequestCurrent(long gate, long match, string token)
    { lock (_gate) return IsOpen && _requestGate == gate && _context?.MatchGeneration == match && LeaseToken == token; }

    private void ScrollDown(JsonObject command)
    {
        var delta = command["wheelDelta"] is null ? -120 : checked((int)Number(command, "wheelDelta"));
        if (delta > -120 || delta < -1440 || delta % 120 != 0)
            throw new InvalidOperationException("WINDOW_SCROLL_DELTA_REJECTED");
        if (!_windowScrollAllowed || _scrollDown is null) throw new InvalidOperationException("WINDOW_SCROLL_NOT_AUTHORIZED");
        if (_request is not null || _source is not null) throw new InvalidOperationException("SOURCE_REQUEST_PENDING");
        var source = Required(command, "sourceLeaseId");
        if (source != _lastSavedSource || Required(command, "pixelSha256") != _lastSavedHash
            || Number(command, "requestOrdinal") != _ordinal || !_scrolledSources.Add(source))
            throw new InvalidOperationException("SCROLL_SOURCE_NOT_SAVED_OR_REUSED");
        // Charge the pulse before calling the adapter: an uncertain send is never retried.
        if (_scrolledSources.Count >= MaxSources || _written >= MaxSources || _attempts >= 32)
            throw new InvalidOperationException("SOURCE_LIMIT_REACHED");
        var c = _context!;
        string[] currentFailures = [];
        var scrollAttempt = new WarehouseScrollAttempt();
        bool Current()
        {
            // Freeze latest first; use a comparison time that follows that read.
            var latest = _policy == CapturePolicy.Delivery ? _latestSummary?.Invoke() : null;
            var now = _clock();
            var checks = new JsonObject { ["leaseOpen"] = IsOpen, ["contextMatches"] = _context == c,
                ["settlementEligible"] = c.SettlementCaptureEligible, ["targetUsable"] = c.TargetUsable,
                ["beforeLeaseDeadline"] = now < _leaseDeadline };
            var details = new JsonObject { ["comparisonNs"] = now, ["leaseDeadlineNs"] = _leaseDeadline };
            if (_policy == CapturePolicy.Delivery) DeliveryScrollCurrent(command, now, checks, details, latest);
            else {
                checks["strictSourcePresent"] = _lastSourceTime > 0;
                var futureComparison = _clock();
                checks["strictSourceNotFuture"] = _lastSourceTime <= futureComparison;
                var ageComparison = _clock();
                checks["strictSourceRecent"] = ageComparison - _lastSourceTime <= FreshnessNs;
                details["strictFutureComparisonNs"] = futureComparison;
                details["strictAgeComparisonNs"] = ageComparison;
            }
            var failures = checks.Where(pair => !pair.Value!.GetValue<bool>()).Select(pair => pair.Key).ToArray();
            currentFailures = failures;
            // A successful message may already have changed the old viewport.
            // This is not input permission or displacement proof: every other
            // lease/proof/scene guard and the adapter's target/map guard remains.
            var postSendContentOnly = _policy == CapturePolicy.Delivery && scrollAttempt.SendSucceeded
                && failures.SequenceEqual(new[] { "scrollContentQuantizationSupported" });
            details["checks"] = checks;
            details["failedChecks"] = new JsonArray(failures.Select(name => JsonValue.Create(name)).ToArray());
            details["guardPhase"] = scrollAttempt.SendSucceeded ? "POST_SEND" : "PRE_SEND";
            details["waitPostScrollEvidence"] = postSendContentOnly;
            details["qualified"] = failures.Length == 0 || postSendContentOnly;
            if (!postSendContentOnly && failures.Contains("scrollContentQuantizationSupported")) PreserveScrollRefusal(command, latest, details);
            LogScroll(command, "lease-qualification", details);
            return failures.Length == 0 || postSendContentOnly;
        }
        if (!Current())
        {
            // Only this pre-adapter failure is known not to have sent input.
            // Consume the old source pulse and require new independent SOURCE
            // support; keep the original lease, deadline and counters.
            if (_policy == CapturePolicy.Delivery && currentFailures.SequenceEqual(new[] { "scrollContentQuantizationSupported" }))
            {
                var recheck = new JsonObject { ["classification"] = "NOT_SENT_CONTENT_SUPPORT_RECHECK",
                    ["sendInterfaceInvoked"] = false, ["sourceLeaseId"] = source,
                    ["failedChecks"] = new JsonArray("scrollContentQuantizationSupported") };
                LogScroll(command, "scroll-ended", (JsonObject)recheck.DeepClone());
                Emit(command, "REJECTED", "SCROLL_CONTENT_CHANGED_BEFORE_SEND", recheck);
                return;
            }
            LogScroll(command, "scroll-ended", new JsonObject { ["classification"] = "NOT_SENT_QUALIFICATION_REJECTED", ["sendInterfaceInvoked"] = false });
            Close("WINDOW_SCROLL_FAILED_OR_TARGET_CHANGED"); return;
        }
        if (!_scrollDown(c with { WheelDelta = delta, ScrollAttempt = scrollAttempt }, Current))
        {
            // This is the *same* content-only pre-send recovery as the outer guard,
            // but only the adapter can prove it never reached the input API.
            // Failed/unknown sends and any other post-send guard loss stop.
            if (_policy == CapturePolicy.Delivery && scrollAttempt.ConfirmedNotSentByCurrentGuard
                && currentFailures.SequenceEqual(new[] { "scrollContentQuantizationSupported" })
                && IsOpen && ReferenceEquals(_context, c) && _clock() < _leaseDeadline)
            {
                var recheck = new JsonObject { ["classification"] = "NOT_SENT_CONTENT_SUPPORT_RECHECK",
                    ["sendInterfaceInvoked"] = false, ["sourceLeaseId"] = source,
                    ["adapterStage"] = scrollAttempt.PreSendCurrentGuardRejection,
                    ["failedChecks"] = new JsonArray("scrollContentQuantizationSupported") };
                LogScroll(command, "scroll-ended", (JsonObject)recheck.DeepClone());
                Emit(command, "REJECTED", "SCROLL_CONTENT_CHANGED_BEFORE_SEND", recheck);
                return;
            }
            LogScroll(command, "scroll-ended", new JsonObject {
                ["classification"] = "ADAPTER_REJECTED_OR_SEND_FAILED",
                ["sendInterfaceInvoked"] = scrollAttempt.SendInterfaceInvoked ? true : null });
            Close("WINDOW_SCROLL_FAILED_OR_TARGET_CHANGED"); return;
        }
        _lastScrollCompletedNs = _clock();
        Emit(command, "SCROLLED", "WINDOW_WHEEL_MESSAGE_SENT", new JsonObject {
            ["direction"] = "DOWN", ["delta"] = delta, ["sourceLeaseId"] = source,
            ["classification"] = "SENT_WAIT_POST_SCROLL_EVIDENCE", ["sendInterfaceInvoked"] = scrollAttempt.SendInterfaceInvoked,
            ["postScrollFrameReceived"] = false, ["displacementVerified"] = false,
            ["scrollRequestCount"] = _scrolledSources.Count, ["messageCompletedNs"] = _lastScrollCompletedNs }, inputActions: true);
    }

    public void Close(string reason)
    {
        if (Volatile.Read(ref _signal) is { } pending) Interlocked.Exchange(ref pending.Cancelled, 1);
        lock (_gate)
        {
        CancelTriggerWatchLocked(reason);
        var opened = _open;
        if (_signal is { } signal) Interlocked.Exchange(ref signal.Cancelled, 1);
        _open = _request = _source = null;
        if (opened is not null) Emit(opened, "CLOSED", reason);
        }
    }

    public void Reject(JsonObject command, string reason) => Emit(command, "REJECTED", reason);

    private bool SameLease(JsonObject command) => _open is not null
        && Text(command, "leaseToken") == LeaseToken
        && Text(command, "reviewSessionId") == Text(_open, "reviewSessionId")
        && Number(command, "reviewGeneration") == Number(_open, "reviewGeneration")
        && Text(command, "recordStableKey") == _context?.RecordKey
        && (_policy != CapturePolicy.Delivery || Number(command, "matchGeneration") == _context?.MatchGeneration)
        && JsonNode.DeepEquals(command["expectedTargetInstance"], _context?.Target);

    private void Emit(JsonObject command, string evt, string? reason, JsonObject? details = null, JsonObject? source = null,
        bool inputActions = false)
    {
        details = details is null ? new JsonObject() : (JsonObject)details.DeepClone();
        details["remainingSourcePages"] = MaxSources - _written;
        details["remainingRawBytes"] = MaxRawBytes - _rawBytes;
        var result = new JsonObject { ["type"] = EventType, ["schemaVersion"] = _policy == CapturePolicy.Delivery ? SchemaV2 : Schema, ["event"] = evt,
            ["capturePolicy"] = _policy, ["matchGeneration"] = _context?.MatchGeneration,
            ["observationSessionId"] = _observation, ["sourceKind"] = "native_wgc", ["inputActions"] = inputActions,
            ["formalHistoryWriter"] = false, ["leaseToken"] = LeaseToken, ["reason"] = reason,
            ["targetInstance"] = _context?.Target.DeepClone(), ["details"] = details?.DeepClone(), ["source"] = source?.DeepClone() };
        if (Text(command, "watchId") is { } watchId) result["watchId"] = watchId;
        foreach (var key in new[] { "commandId", "reviewSessionId", "reviewGeneration", "recordStableKey", "nonce", "requestOrdinal" })
            result[key] = key is "reviewGeneration" or "requestOrdinal" ? Number(command, key)
                : Text(command, key) is { Length: <= 256 } value ? JsonValue.Create(value) : null;
        _emit(result);
    }

    private static bool ValidGeometry(int w, int h) => w > 0 && h > 0
        && w <= ProtocolConstants.MaxFrameWidth && h <= ProtocolConstants.MaxFrameHeight;
    private static string? Text(JsonObject j, string k) => j[k] is JsonValue v && v.TryGetValue<string>(out var s) ? s : null;
    private static string Required(JsonObject j, string k) => Text(j, k) is { Length: > 0 and <= 256 } s ? s : throw new InvalidOperationException("INVALID_" + k);
    private static long Number(JsonObject j, string k) => j[k] is JsonValue v
        ? v.TryGetValue<long>(out var n) ? n : v.TryGetValue<int>(out var i) ? i : -1 : -1;

    private static void WriteNewBmp(string path, WarehouseSourceFrame f)
    {
        using var stream = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None);
        using (var writer = new BinaryWriter(stream, Encoding.UTF8, leaveOpen: true))
        {
            writer.Write((byte)'B'); writer.Write((byte)'M'); writer.Write(checked(54 + f.Pixels.Length));
            writer.Write(0); writer.Write(54); writer.Write(40); writer.Write(f.Width); writer.Write(-f.Height);
            writer.Write((short)1); writer.Write((short)32); writer.Write(0); writer.Write(f.Pixels.Length);
            writer.Write(2835); writer.Write(2835); writer.Write(0); writer.Write(0); writer.Write(f.Pixels);
            writer.Flush();
        }
        stream.Flush(flushToDisk: true);
    }
}
