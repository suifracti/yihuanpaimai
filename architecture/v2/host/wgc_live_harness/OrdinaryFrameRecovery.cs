using System.Text.Json.Nodes;

namespace WgcLiveHarness;

internal sealed record OrdinaryFrameDiscard(string CaptureId, string SessionId, long PoolEpoch,
    long CaptureScopeEpoch, long Sequence, long ReadbackNs, long ComparedAtNs)
{
    public string Reason => "DELIVERY_LOCAL_USE_EXPIRED";
    public static OrdinaryFrameDiscard From(CapturedBgraFrame frame, long now) => new(
        frame.DeliveryProof!.CaptureId, frame.DeliveryProof.ObservationSessionId, frame.DeliveryProof.PoolEpoch,
        frame.CaptureScopeEpoch, frame.AcquisitionSequence, frame.CaptureTimestampNs, now);
    public JsonObject ToJson() => new() { ["reason"] = Reason, ["captureId"] = CaptureId,
        ["observationSessionId"] = SessionId, ["poolEpoch"] = PoolEpoch, ["captureScopeEpoch"] = CaptureScopeEpoch,
        ["acquisitionSequence"] = Sequence, ["readbackTimestampNs"] = ReadbackNs, ["comparedAtNs"] = ComparedAtNs,
        ["discarded"] = true, ["sourceAuthority"] = false, ["inputActions"] = false };
}

internal sealed class OrdinaryFrameExpiredException(OrdinaryFrameDiscard discard) : Exception(discard.Reason)
{
    public OrdinaryFrameDiscard Discard { get; } = discard;
}

// One retry window for ordinary FRAME admission, never a SOURCE request.
internal sealed class OrdinaryFrameRecovery(int frameWaitMs)
{
    private readonly long _waitNs = Math.Clamp(frameWaitMs, 1, 5000) * 1_000_000L;
    public OrdinaryFrameDiscard? First { get; private set; }
    public long DeadlineNs { get; private set; }
    public bool Expired(long now) => First is not null && now >= DeadlineNs;
    public int RemainingWaitMs(long now, int normalWaitMs) => First is null ? normalWaitMs
        : checked((int)Math.Max(1, Math.Min(normalWaitMs, (DeadlineNs - now + 999_999) / 1_000_000)));
    public static bool Recoverable(CapturedBgraFrame frame, long now) => frame.DeliveryProof is { } proof
        && proof.IsLocalAgeExpired(now) && frame.CaptureTimestampNs == proof.ReadbackCompletedNs
        && frame.SourceTimestampNs == proof.SourceNs && frame.AcquisitionSequence == proof.AcquisitionSequence;
    public string? ContextRejection(CapturedBgraFrame frame) => First is not { } first ? null
        : frame.DeliveryProof is not { } proof || proof.ObservationSessionId != first.SessionId
            || proof.PoolEpoch != first.PoolEpoch || frame.CaptureScopeEpoch != first.CaptureScopeEpoch
            ? "ORDINARY_FRAME_RECOVERY_SCOPE_CHANGED"
        : frame.CaptureTimestampNs != proof.ReadbackCompletedNs || frame.SourceTimestampNs != proof.SourceNs
            || frame.AcquisitionSequence != proof.AcquisitionSequence ? "DELIVERY_FRAME_BINDING_MISMATCH"
        : frame.AcquisitionSequence <= first.Sequence || frame.CaptureTimestampNs <= first.ReadbackNs
            ? "ORDINARY_FRAME_RECOVERY_INDEPENDENCE_UNPROVEN" : null;
    public void Discard(CapturedBgraFrame frame, long now)
    {
        if (!Recoverable(frame, now)) throw new InvalidOperationException("ORDINARY_FRAME_NOT_RECOVERABLE");
        if (First is null) Begin(OrdinaryFrameDiscard.From(frame, now));
    }
    public void Begin(OrdinaryFrameDiscard first)
    {
        if (First is not null) return;
        First = first; DeadlineNs = checked(first.ComparedAtNs + _waitNs);
    }
    public void Accepted() { First = null; DeadlineNs = 0; }
}
