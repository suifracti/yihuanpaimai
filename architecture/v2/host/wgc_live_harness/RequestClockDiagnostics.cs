using System.Collections.Generic;
using System.Diagnostics;
using System.Text.Json;
using NteHost.Protocol;

namespace WgcLiveHarness;

// Opt-in QA telemetry. Samples use the existing conversion and are never
// corrected or substituted for a rejected WGC timestamp.
internal sealed record QpcClockSample(long RawTicks, long FrequencyHz,
    long WholeSeconds, long RemainderTicks, long Nanoseconds)
{
    public static QpcClockSample Read()
    {
        var ticks = Stopwatch.GetTimestamp();
        var ns = ProtocolClock.TicksToNs(ticks);
        var frequency = ProtocolClock.Frequency;
        return new(ticks, frequency, ticks / frequency, ticks % frequency, ns);
    }
}

internal sealed class RequestClockDiagnostics(long requestNs, long deadlineNs)
{
    private const int MaxComparisons = 32;
    private readonly List<object> _comparisons = new();
    private long? _pendingSourceTicks;
    private int _totalComparisons;
    private object? _readback;
    public string? Failure { get; set; }

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
            comparison = sample, aheadNs = sourceNs - sample.Nanoseconds });
    }

    public void Readback(long ticks, QpcClockSample sample) =>
        _readback = new { sourceSystemRelativeTicks = ticks,
            sourceTimestampNs = checked(ticks * 100L), clock = sample };

    public string ToJson() => JsonSerializer.Serialize(new {
        schemaVersion = "request-clock-diagnostic-v1", requestTimestampNs = requestNs,
        deadlineNs, sourceTickUnitNs = 100, qpcConversion = "wholeSeconds*1000000000+remainderTicks*1000000000/frequencyHz",
        comparisons = _comparisons, totalComparisons = _totalComparisons,
        truncatedComparisons = _totalComparisons - _comparisons.Count,
        pendingSourceSystemRelativeTicks = _pendingSourceTicks,
        readbackStatus = _readback is null ? "NOT_REACHED" : "READ_BACK",
        readback = _readback, failure = Failure,
    }, new JsonSerializerOptions { PropertyNamingPolicy = JsonNamingPolicy.CamelCase });
}
