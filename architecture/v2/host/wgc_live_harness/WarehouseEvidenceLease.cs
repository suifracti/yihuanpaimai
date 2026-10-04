using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using NteHost.Protocol;

namespace WgcLiveHarness;

internal sealed record WarehouseSourceContext(string RecordKey, JsonObject Target, string ClientMap,
    int Width, int Height, bool FrozenSettlement, bool TargetUsable, long AbsoluteDeadlineNs);

internal sealed record WarehouseSourceFrame(int Width, int Height, int Stride, byte[] Pixels,
    long SourceTimestampNs, long ReadbackTimestampNs, string CapturedAtUtc, long Sequence,
    string WorkerPixelSha256, long WorkerSequence);

/// <summary>Host-local, explicitly requested source leases. No business/worker mutations.</summary>
internal sealed class WarehouseEvidenceLease : IDisposable
{
    public const string ControlType = "native_warehouse_evidence_control";
    public const string EventType = "native_warehouse_evidence";
    public const string Schema = "native-warehouse-source.v1";
    public const string PngEncoding = "opencv-bgr8-png-bound.v1";
    public const int MaxSources = 16;
    public const long MaxRawBytes = 128L * 1024 * 1024;
    public const long MaxPngBytes = 64L * 1024 * 1024;
    private const long SourceWaitNs = 5_000_000_000;
    private const long FreshnessNs = 2_000_000_000;
    private readonly string _root, _observation;
    private readonly Action<JsonObject> _emit;
    private readonly Func<long> _clock;
    private readonly Func<WarehouseSourceContext, Func<bool>, bool>? _scrollDown;
    private int _transportStopped;
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
    private sealed record Signal(string Review, int Generation, string Token) { public int Cancelled; }
    public string? LeaseToken { get; private set; }
    public bool IsOpen => Volatile.Read(ref _transportStopped) == 0 && _open is not null
        && Volatile.Read(ref _signal) is { } signal && Volatile.Read(ref signal.Cancelled) == 0;
    public int WrittenSources => _written;
    public long? PendingRequestGateNs => IsOpen && _request is not null && _source is null ? _requestGate : null;
    public long PendingRequestDeadlineNs => _requestDeadline;

    public WarehouseEvidenceLease(string workRoot, string observation, Action<JsonObject> emit, Func<long>? clock = null,
        Func<WarehouseSourceContext, Func<bool>, bool>? scrollDown = null)
    {
        _root = Path.GetFullPath(Path.Combine(workRoot, "warehouse-sources"));
        _observation = observation; _emit = emit; _clock = clock ?? ProtocolClock.NowNs;
        _scrollDown = scrollDown;
    }

    public void UpdateContext(WarehouseSourceContext context)
    {
        if (_open is not null && (_context is null || context.RecordKey != _context.RecordKey
                || context.ClientMap != _context.ClientMap || !JsonNode.DeepEquals(context.Target, _context.Target)
                || !context.FrozenSettlement || !context.TargetUsable)) Close("SOURCE_SCOPE_CHANGED");
        if (_budgetRecord != context.RecordKey)
        {
            _budgetRecord = context.RecordKey; _budgetMap = context.ClientMap;
            _written = _attempts = 0; _rawBytes = _lastSequence = _lastSourceTime = 0; _savedHashes.Clear();
        }
        _context = context;
        Tick();
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
    }

    public void Dispose() => Close("HOST_SOURCE_STOPPED");

    public void Handle(JsonObject command)
    {
        try
        {
            if (Encoding.UTF8.GetByteCount(command.ToJsonString()) > 16 * 1024)
                throw new InvalidOperationException("SOURCE_MESSAGE_TOO_LARGE");
            if (Text(command, "type") != ControlType || Text(command, "schemaVersion") != Schema)
                throw new InvalidOperationException("UNSUPPORTED_SOURCE_SCHEMA");
            if (Text(command, "observationSessionId") != _observation)
                throw new InvalidOperationException("STALE_OBSERVATION_SESSION");
            var op = Required(command, "operation");
            Required(command, "commandId"); Required(command, "nonce");
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
            Tick();
            if (!IsOpen) throw new InvalidOperationException("SOURCE_LEASE_EXPIRED");
            if (op == "REQUEST_PAGE") Request(command);
            else if (op == "ACK_SOURCE") Ack(command);
            else if (op == "SCROLL_DOWN") ScrollDown(command);
            else throw new InvalidOperationException("UNKNOWN_SOURCE_OPERATION");
        }
        catch (Exception ex) when (ex is InvalidOperationException or FormatException or OverflowException)
        { Emit(command, "REJECTED", ex.Message); }
    }

    private void Open(JsonObject command)
    {
        if (Volatile.Read(ref _transportStopped) != 0) throw new InvalidOperationException("SOURCE_TRANSPORT_CLOSED");
        if (IsOpen) throw new InvalidOperationException("SOURCE_LEASE_ALREADY_OPEN");
        var c = _context ?? throw new InvalidOperationException("SOURCE_CONTEXT_UNAVAILABLE");
        if (!c.TargetUsable || !c.FrozenSettlement) throw new InvalidOperationException("SETTLEMENT_NOT_FROZEN_OR_TARGET_UNUSABLE");
        if (!ValidGeometry(c.Width, c.Height)) throw new InvalidOperationException("FIXED_V1_GEOMETRY_REJECTED");
        if (Required(command, "recordStableKey") != c.RecordKey
            || !JsonNode.DeepEquals(command["expectedTargetInstance"], c.Target))
            throw new InvalidOperationException("SOURCE_SCOPE_CHANGED");
        if (_clock() >= c.AbsoluteDeadlineNs) throw new InvalidOperationException("ABSOLUTE_SETTLEMENT_BUDGET_EXPIRED");
        if (_written >= MaxSources || _rawBytes >= MaxRawBytes || _attempts >= 32 || c.ClientMap != _budgetMap)
            throw new InvalidOperationException("SOURCE_LIMIT_REACHED");
        _open = (JsonObject)command.DeepClone(); _request = _source = null; _ordinal = 0;
        _windowScrollAllowed = command["allowWindowScroll"] is JsonValue flag
            && flag.TryGetValue<bool>(out var allow) && allow;
        _lastSavedSource = _lastSavedHash = null; _scrolledSources.Clear();
        LeaseToken = Guid.NewGuid().ToString("N");
        Volatile.Write(ref _signal, new Signal(Required(command, "reviewSessionId"), (int)Number(command, "reviewGeneration"), LeaseToken));
        _leaseDeadline = Math.Min(c.AbsoluteDeadlineNs, checked(_clock() + 70_000_000_000));
        Emit(command, "OPENED", null, new JsonObject {
            ["deadlineNs"] = _leaseDeadline, ["maxWidth"] = ProtocolConstants.MaxFrameWidth,
            ["maxHeight"] = ProtocolConstants.MaxFrameHeight, ["remainingSourcePages"] = MaxSources - _written,
            ["remainingRawBytes"] = MaxRawBytes - _rawBytes, ["maxPngBytes"] = MaxPngBytes,
            ["pngEncoding"] = PngEncoding, ["clientMap"] = c.ClientMap,
            ["windowScrollSupported"] = _windowScrollAllowed && _scrollDown is not null,
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
        _requestGate = _clock(); _requestDeadline = Math.Min(_leaseDeadline, checked(_requestGate + SourceWaitNs));
        _request = (JsonObject)command.DeepClone();
        Emit(command, "RESULT", "SOURCE_REQUESTED");
    }

    // OpenCV's current BGR8 PNG contains 3 bytes/pixel plus row filter and bounded zlib/chunk overhead.
    // This deliberately conservative bound is checked upstream; accepted PNG bytes remain exact downstream.
    public static long PngUpperBound(int width, int height) => checked(4L * width * height + 65536);

    public void Tick()
    {
        if (_open is null) return;
        if (!IsOpen) { Close("MANUAL_SOURCE_CANCELLED"); return; }
        if (_clock() >= _leaseDeadline) { Close("ABSOLUTE_SETTLEMENT_BUDGET_EXPIRED"); return; }
        if ((_request is not null && _clock() >= _requestDeadline)
            || (_source is not null && _clock() >= _requestDeadline))
        { var failed = _request ?? _open; _request = _source = null; Emit(failed, "REJECTED", "SOURCE_REQUEST_TIMEOUT"); }
    }

    public bool TryPublish(WarehouseSourceFrame frame, Func<bool> revalidateTarget)
    {
        Tick();
        var request = _request; var c = _context;
        if (request is null || c is null || !IsOpen || _source is not null) return false;
        if (!revalidateTarget()) { Close("SOURCE_TARGET_CHANGED"); return false; }
        var now = _clock();
        if (frame.SourceTimestampNs <= _requestGate || frame.SourceTimestampNs <= _lastSourceTime
            || frame.SourceTimestampNs > now || now - frame.SourceTimestampNs > FreshnessNs
            || frame.Sequence <= _lastSequence) return false;
        if (frame.Width != c.Width || frame.Height != c.Height || !ValidGeometry(frame.Width, frame.Height)
            || frame.Stride != frame.Width * 4 || frame.Pixels.LongLength != 4L * frame.Width * frame.Height)
        { Close("SOURCE_GEOMETRY_CHANGED"); return false; }
        var pixelHash = Convert.ToHexString(SHA256.HashData(frame.Pixels)).ToLowerInvariant();
        if (frame.Sequence != frame.WorkerSequence || !string.Equals(pixelHash, frame.WorkerPixelSha256, StringComparison.Ordinal))
        { _request = null; Emit(request, "REJECTED", "WORKER_SOURCE_HASH_MISMATCH"); return false; }
        // Hashing/target checks may race with a reader cancellation. Recheck at file admission.
        Tick();
        if (!IsOpen || _request is null) return false;
        if (_savedHashes.Contains(pixelHash))
        {
            if (!revalidateTarget() || !IsOpen) { Close("SOURCE_TARGET_CHANGED"); return false; }
            _request = null;
            Emit(request, "RESULT", "DUPLICATE_PAGE", new JsonObject {
                ["sourceTimestampNs"] = frame.SourceTimestampNs, ["requestGateNs"] = _requestGate,
                ["pixelSha256"] = pixelHash, ["frameSequence"] = frame.Sequence, ["clientMap"] = c.ClientMap });
            return false;
        }
        var sourceId = Guid.NewGuid().ToString("N");
        var path = Path.Combine(_root, sourceId + ".bmp");
        // Charge potential files before IO, including failed/partially written originals; never silently delete.
        _written++; _rawBytes += 54L + frame.Pixels.LongLength;
        _lastSequence = frame.Sequence; _lastSourceTime = frame.SourceTimestampNs;
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

    private void ScrollDown(JsonObject command)
    {
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
        bool Current() => IsOpen && _context == c && _clock() < _leaseDeadline;
        if (!Current() || !_scrollDown(c, Current))
        { Close("WINDOW_SCROLL_FAILED_OR_TARGET_CHANGED"); return; }
        Emit(command, "SCROLLED", "WINDOW_WHEEL_MESSAGE_SENT", new JsonObject {
            ["direction"] = "DOWN", ["delta"] = -120, ["sourceLeaseId"] = source,
            ["scrollRequestCount"] = _scrolledSources.Count }, inputActions: true);
    }

    public void Close(string reason)
    {
        var opened = _open;
        if (_signal is { } signal) Interlocked.Exchange(ref signal.Cancelled, 1);
        _open = _request = _source = null;
        if (opened is not null) Emit(opened, "CLOSED", reason);
    }

    public void Reject(JsonObject command, string reason) => Emit(command, "REJECTED", reason);

    private bool SameLease(JsonObject command) => _open is not null
        && Text(command, "leaseToken") == LeaseToken
        && Text(command, "reviewSessionId") == Text(_open, "reviewSessionId")
        && Number(command, "reviewGeneration") == Number(_open, "reviewGeneration")
        && Text(command, "recordStableKey") == _context?.RecordKey
        && JsonNode.DeepEquals(command["expectedTargetInstance"], _context?.Target);

    private void Emit(JsonObject command, string evt, string? reason, JsonObject? details = null, JsonObject? source = null,
        bool inputActions = false)
    {
        details = details is null ? new JsonObject() : (JsonObject)details.DeepClone();
        details["remainingSourcePages"] = MaxSources - _written;
        details["remainingRawBytes"] = MaxRawBytes - _rawBytes;
        var result = new JsonObject { ["type"] = EventType, ["schemaVersion"] = Schema, ["event"] = evt,
            ["observationSessionId"] = _observation, ["sourceKind"] = "native_wgc", ["inputActions"] = inputActions,
            ["formalHistoryWriter"] = false, ["leaseToken"] = LeaseToken, ["reason"] = reason,
            ["targetInstance"] = _context?.Target.DeepClone(), ["details"] = details?.DeepClone(), ["source"] = source?.DeepClone() };
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
