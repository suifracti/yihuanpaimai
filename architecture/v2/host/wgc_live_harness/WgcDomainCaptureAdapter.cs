using NteHost.DomainActions;

namespace WgcLiveHarness;

// The NativeObservationService owner calls this ONLY on an independently requested
// capture.CaptureAfterRequest result. No Engine frame/context cache is accepted.
internal static class WgcDomainCaptureAdapter
{
    public static CapturedBgraFrame CaptureForInput(Func<int, long, long, CapturedBgraFrame> capture,
        long requestNs, long deadlineNs, Func<long> clock)
    {
        CapturedBgraFrame? last = null;
        for (int sample = 0; sample < 4 && clock() < deadlineNs; sample++)
        {
            var remainingMs = Math.Max(1, (deadlineNs - clock()) / 1_000_000);
            var frame = capture((int)Math.Min(1500, remainingMs), requestNs, deadlineNs);
            if (last is not null && frame.CaptureScopeEpoch != last.CaptureScopeEpoch)
                throw new InvalidOperationException("input-capture-scope-changed");
            last = frame;
            var now = clock();
            var proof = frame.DeliveryProof;
            // Post-empty delivery can still carry a pre-request source marker.
            // Only that otherwise-valid case waits for another independent image.
            // Invalid/future/stalled/expired proofs keep their original rejection.
            bool preRequestDelivery = frame.SourceTimestampNs <= requestNs && proof is not null
                && proof.RequestNs == requestNs && proof.DeadlineNs == deadlineNs
                && proof.SourceNs == frame.SourceTimestampNs && proof.ReadbackCompletedNs == frame.CaptureTimestampNs
                && proof.AcquisitionSequence == frame.AcquisitionSequence
                && proof.SourceMarkerProgress && proof.OriginStatus == "CONSISTENT_AT_READ"
                && proof.Rejection(now, 500_000_000) is null;
            if (!preRequestDelivery) return frame;
        }
        // An exhausted wait never upgrades the last pre-request delivery.
        // FromIndependentCapture will reject it by the unchanged source gate.
        return last ?? throw new TimeoutException("input-post-request-source-timeout");
    }

    public static NativeDomainFrame? FromIndependentCapture(CapturedBgraFrame frame, ActionScope scope,
        ClientGeometry geometry, long requestNs, long comparisonNs, WindowBinding captureOwner, long captureScopeEpoch)
    {
        if (!scope.SourceQualified || captureOwner != scope.Window || captureScopeEpoch <= 0
            || frame.CaptureScopeEpoch != captureScopeEpoch || requestNs <= 0 || frame.SourceTimestampNs <= requestNs
            || frame.SourceTimestampNs > comparisonNs || frame.CaptureTimestampNs > comparisonNs
            || frame.CaptureTimestampNs < frame.SourceTimestampNs || comparisonNs - frame.CaptureTimestampNs > 500_000_000
            || frame.AcquisitionSequence <= 0 || frame.Width != geometry.Width || frame.Height != geometry.Height)
            return null;
        if (frame.DeliveryProof is { } proof && (!proof.Qualified || !proof.SourceMarkerProgress
            || proof.OriginStatus != "CONSISTENT_AT_READ" || proof.ObservationSessionId != scope.ObservationSessionId
            || proof.AcquisitionSequence != frame.AcquisitionSequence || proof.SourceNs != frame.SourceTimestampNs
            || proof.RequestNs != requestNs || proof.Rejection(comparisonNs, 500_000_000) != null)) return null;
        var qualified = scope with { SourceSequence = frame.AcquisitionSequence, CapturedNs = frame.CaptureTimestampNs };
        return new(qualified, geometry, frame.Pixels, frame.Stride);
    }
}
