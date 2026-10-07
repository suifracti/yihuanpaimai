using System.Collections.Generic;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Text.Json;
using NteHost.Protocol;

namespace WgcLiveHarness;

// Bounded QA/observation telemetry. Samples use the existing conversion and are never
// corrected or substituted for a rejected WGC timestamp.
internal sealed record QpcClockSample(long RawTicks, long FrequencyHz,
    long WholeSeconds, long RemainderTicks, long Nanoseconds)
{
    public int ManagedThreadId { get; init; } = Environment.CurrentManagedThreadId;
    public static QpcClockSample Read()
    {
        var ticks = Stopwatch.GetTimestamp();
        var ns = ProtocolClock.TicksToNs(ticks);
        var frequency = ProtocolClock.Frequency;
        return new(ticks, frequency, ticks / frequency, ticks % frequency, ns);
    }
}

internal sealed class RequestClockDiagnostics(long requestNs, long deadlineNs, QpcClockSample? requestClock = null)
{
    private const int MaxComparisons = 32;
    private readonly List<object> _comparisons = new();
    private long? _pendingSourceTicks;
    private int _totalComparisons;
    private object? _readback;
    private readonly Queue<object> _operations = new();
    private long _operationCount;
    private readonly QpcClockSample _entryClock = QpcClockSample.Read();
    public string? Failure { get; set; }

    public void Operation(string stage, QpcClockSample before, QpcClockSample after, object? details = null)
    {
        if (_operations.Count == MaxComparisons) _operations.Dequeue();
        _operations.Enqueue(new { stage, before, after, details });
        _operationCount++;
    }

    // Independent Win32 sample AFTER the decision sample. It diagnoses the
    // managed clock; it never replaces or delays that sample's gate value.
    private static object NativeAuthority()
    {
        var before = QpcClockSample.Read();
        var counterOk = QueryPerformanceCounter(out var rawTicks);
        var frequencyOk = QueryPerformanceFrequency(out var frequencyHz);
        var after = QpcClockSample.Read();
        return new { before, counterOk, rawTicks, frequencyOk, frequencyHz, after };
    }
    [DllImport("kernel32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool QueryPerformanceCounter(out long ticks);
    [DllImport("kernel32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool QueryPerformanceFrequency(out long frequency);

    public long Source(long rawSystemRelativeTicks)
    {
        _pendingSourceTicks = rawSystemRelativeTicks;
        return checked(rawSystemRelativeTicks * 100L);
    }

    public long SelectionClock()
    {
        var sample = QpcClockSample.Read();
        if (_pendingSourceTicks is { } ticks)
        {
            _pendingSourceTicks = null;
            RecordComparison(ticks, sample);
        }
        return sample.Nanoseconds;
    }

    internal void RecordComparison(long ticks, QpcClockSample sample)
    {
        var sourceNs = checked(ticks * 100L);
        if (_comparisons.Count == MaxComparisons) _comparisons.RemoveAt(0);
        _totalComparisons++;
        _comparisons.Add(new { sourceSystemRelativeTicks = ticks, sourceTimestampNs = sourceNs,
            comparison = sample, aheadNs = sourceNs - sample.Nanoseconds,
            nativeAuthorityAfterDecision = NativeAuthority() });
    }

    public void Readback(long ticks, QpcClockSample sample) =>
        _readback = new { sourceSystemRelativeTicks = ticks,
            sourceTimestampNs = checked(ticks * 100L), clock = sample };

    public string ToJson() => JsonSerializer.Serialize(new {
        schemaVersion = "request-clock-diagnostic-v2", requestTimestampNs = requestNs,
        callerRequestClock = requestClock, entryClock = _entryClock,
        requestNote = "Caller gate is unchanged; entryClock is a later observation, not reconstructed request ticks.",
        deadlineNs, sourceTickUnitNs = 100, qpcConversion = "wholeSeconds*1000000000+remainderTicks*1000000000/frequencyHz",
        comparisons = _comparisons, totalComparisons = _totalComparisons,
        truncatedComparisons = _totalComparisons - _comparisons.Count,
        pendingSourceSystemRelativeTicks = _pendingSourceTicks,
        operations = _operations, totalOperations = _operationCount,
        truncatedOperations = _operationCount - _operations.Count,
        readbackStatus = _readback is null ? "NOT_REACHED" : "READ_BACK",
        readback = _readback, failure = Failure,
    }, new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.CamelCase });
}
