using NteHost.DomainActions;

namespace WgcLiveHarness;

// The NativeObservationService owner calls this ONLY on an independently requested
// capture.CaptureAfterRequest result. No Engine frame/context cache is accepted.
internal static class WgcDomainCaptureAdapter
{
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
