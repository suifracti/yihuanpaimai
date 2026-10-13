using System.Text.Json.Nodes;

namespace WgcLiveHarness;

// No new ordinary observation during a loading/static interval is not a
// capture-owner failure. Each poll remains cancellable; explicit SOURCE jobs
// never use this exception or retry their original deadline.
internal sealed class OrdinaryFrameUnavailableException(Exception cause)
    : TimeoutException("ordinary-frame-waiting", cause)
{
    public static bool IsSelectionTimeout(Exception cause) => cause is TimeoutException && cause.Message is
        "DELIVERY_DEADLINE" or "Request-frame selection reached its original deadline."
        or "Explicit frame request reached its original deadline.";
}

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

// Keep the first discarded ordinary frame for diagnostics and scope checking.
// Local expiry cannot impose a total loading timeout. SOURCE deadlines are
// independent; every newly accepted ordinary frame still passes its 2s gate.
internal sealed class OrdinaryFrameRecovery
{
    public OrdinaryFrameDiscard? First { get; private set; }
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
        First = first;
    }
    public void Accepted() { First = null; }
}
