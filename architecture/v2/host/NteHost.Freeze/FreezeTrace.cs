using System;
using System.Collections.Generic;
using System.Linq;

namespace NteHost.Freeze;

/// <summary>
/// One ordered, immutable audit record. The CURRENT_SCOPE requires that "freeze / rearm /
/// event 顺序可完整 trace", so every event — including the rejected ones — produces exactly
/// one record with a monotonic sequence number, the state before and after, and the reason
/// set before and after. A rejected event is recorded with <see cref="Applied"/> = false and
/// an unchanged after-state, which is what makes the whole history replayable.
/// </summary>
public sealed class FreezeTraceRecord
{
    public int Seq { get; init; }
    public string Event { get; init; } = string.Empty;
    public bool Applied { get; init; }
    public string StateBefore { get; init; } = string.Empty;
    public string StateAfter { get; init; } = string.Empty;
    public IReadOnlyList<string> ReasonsBefore { get; init; } = Array.Empty<string>();
    public IReadOnlyList<string> ReasonsAfter { get; init; } = Array.Empty<string>();
    public long GenerationBefore { get; init; }
    public long GenerationAfter { get; init; }
    public string? Reason { get; init; }
    public string? Outcome { get; init; }
    public string? Detail { get; init; }

    /// <summary>Machine-readable failure code when the event was refused.</summary>
    public string? ErrorCode { get; init; }
}

public sealed class FreezeTrace
{
    private readonly List<FreezeTraceRecord> _records = new();

    public IReadOnlyList<FreezeTraceRecord> Records => _records;

    public int Count => _records.Count;

    internal FreezeTraceRecord Append(
        int seq,
        FreezeEventKind eventKind,
        bool applied,
        FreezeState stateBefore,
        FreezeState stateAfter,
        IEnumerable<FreezeReason> reasonsBefore,
        IEnumerable<FreezeReason> reasonsAfter,
        long generationBefore,
        long generationAfter,
        FreezeReason? reason = null,
        string? outcome = null,
        string? detail = null,
        string? errorCode = null)
    {
        var record = new FreezeTraceRecord
        {
            Seq = seq,
            Event = eventKind.ToString(),
            Applied = applied,
            StateBefore = stateBefore.ToString(),
            StateAfter = stateAfter.ToString(),
            ReasonsBefore = reasonsBefore.Select(FreezeNames.Of).ToArray(),
            ReasonsAfter = reasonsAfter.Select(FreezeNames.Of).ToArray(),
            GenerationBefore = generationBefore,
            GenerationAfter = generationAfter,
            Reason = reason is null ? null : FreezeNames.Of(reason.Value),
            Outcome = outcome,
            Detail = detail,
            ErrorCode = errorCode,
        };

        _records.Add(record);
        return record;
    }
}

public static class FreezeNames
{
    public static string Of(FreezeReason reason) => reason.ToString();
}
