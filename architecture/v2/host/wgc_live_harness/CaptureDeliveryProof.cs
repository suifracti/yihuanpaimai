using System.Text.Json;
using System.Text.Json.Nodes;
using NteHost.Protocol;

namespace WgcLiveHarness;

internal static class CapturePolicy
{
    public const string Strict = "wgc-origin-strict-v1", Delivery = "wgc-delivery-v1";
    public static string Parse(string value) => value is Strict or Delivery ? value
        : throw new ArgumentException("invalid-capture-freshness-policy");
}

internal sealed record CaptureDeliveryProof(string ObservationSessionId, long PoolEpoch, long AcquisitionSequence,
    long RequestNs, long DeadlineNs, long EmptyBoundaryNs, long DequeueBeforeNs, long DequeueAfterNs,
    QpcClockSample GetterBefore, QpcClockSample Comparison, long SourceTicks, long RepeatedSourceTicks,
    long PreviousMarkerNs, long ReadbackBeforeNs, long ReadbackCompletedNs)
{
    public const string RetainedBoundary = "retained-pool-buffers.v1";
    public long ReleaseCompletedNs { get; init; }
    public int DrainTakeCount { get; init; }
    public int BoundaryHeldCount { get; init; }
    public long ReadbackSourceTicks { get; init; } = SourceTicks;
    public string CaptureId => $"{ObservationSessionId}/{PoolEpoch}/{AcquisitionSequence}";
    public long SourceNs => checked(SourceTicks * 100);
    public bool SourceMarkerProgress => SourceNs > PreviousMarkerNs;
    public string OriginStatus => SourceTicks != RepeatedSourceTicks || SourceTicks != ReadbackSourceTicks ? "CHANGED_ON_SAME_FRAME"
        : SourceTicks <= 0 ? "NONPOSITIVE" : SourceNs > Comparison.Nanoseconds ? "FUTURE_AT_READ"
        : !SourceMarkerProgress ? "STALLED_OR_REORDERED" : "CONSISTENT_AT_READ";
    public bool Qualified => RequestNs > 0 && DeadlineNs > ReadbackCompletedNs
        && DrainTakeCount is >= 1 and <= 3 && BoundaryHeldCount == DrainTakeCount - 1
        && RequestNs <= EmptyBoundaryNs && EmptyBoundaryNs <= ReleaseCompletedNs && ReleaseCompletedNs <= DequeueBeforeNs
        && DequeueBeforeNs <= DequeueAfterNs && DequeueAfterNs <= GetterBefore.Nanoseconds
        && GetterBefore.Nanoseconds <= Comparison.Nanoseconds && Comparison.Nanoseconds <= ReadbackBeforeNs
        && ReadbackBeforeNs <= ReadbackCompletedNs && SourceTicks == RepeatedSourceTicks && SourceTicks == ReadbackSourceTicks && SourceTicks > 0
        && SourceNs >= PreviousMarkerNs && Comparison.FrequencyHz == ProtocolClock.Frequency
        && GetterBefore.FrequencyHz == Comparison.FrequencyHz && GetterBefore.Nanoseconds == ProtocolClock.TicksToNs(GetterBefore.RawTicks)
        && Comparison.Nanoseconds == ProtocolClock.TicksToNs(Comparison.RawTicks);
    public string? Rejection(long now, long maxAge = 2_000_000_000) => !Qualified ? "DELIVERY_PROOF_INVALID"
        : now < ReadbackCompletedNs || now - ReadbackCompletedNs > maxAge ? "DELIVERY_LOCAL_USE_EXPIRED" : null;
    public JsonObject ToJson() => new()
    {
        ["schemaVersion"] = "capture-delivery-proof.v2", ["capturePolicy"] = CapturePolicy.Delivery,
        ["boundaryKind"] = RetainedBoundary, ["poolBufferCount"] = 2,
        ["drainTakeCount"] = DrainTakeCount, ["boundaryHeldCount"] = BoundaryHeldCount,
        ["releaseCompletedNs"] = ReleaseCompletedNs,
        ["captureId"] = CaptureId, ["observationSessionId"] = ObservationSessionId,
        ["poolEpoch"] = PoolEpoch, ["acquisitionSequence"] = AcquisitionSequence,
        ["requestNs"] = RequestNs, ["deadlineNs"] = DeadlineNs, ["emptyBoundaryNs"] = EmptyBoundaryNs,
        ["dequeueBeforeNs"] = DequeueBeforeNs, ["dequeueAfterNs"] = DequeueAfterNs,
        ["getterBefore"] = JsonSerializer.SerializeToNode(GetterBefore, Options),
        ["comparison"] = JsonSerializer.SerializeToNode(Comparison, Options),
        ["sourceTicks"] = SourceTicks, ["repeatedSourceTicks"] = RepeatedSourceTicks,
        ["readbackSourceTicks"] = ReadbackSourceTicks, ["futureAtRead"] = SourceNs > Comparison.Nanoseconds,
        ["sourceTimestampNs"] = SourceNs, ["previousMarkerNs"] = PreviousMarkerNs,
        ["readbackBeforeNs"] = ReadbackBeforeNs, ["readbackCompletedNs"] = ReadbackCompletedNs,
        ["originStatus"] = OriginStatus, ["originStrictQualified"] = Qualified && SourceMarkerProgress && SourceNs > RequestNs && SourceNs <= Comparison.Nanoseconds,
        ["sourceMarkerProgress"] = SourceMarkerProgress, ["deliveryQualified"] = Qualified,
        ["evidenceMeaning"] = "post-empty delivery; render-after-request and absolute source age unproven",
    };
    private static readonly JsonSerializerOptions Options = new() { PropertyNamingPolicy = JsonNamingPolicy.CamelCase };
}
