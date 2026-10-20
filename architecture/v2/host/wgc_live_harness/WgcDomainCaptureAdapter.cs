using NteHost.DomainActions;

namespace WgcLiveHarness;

// A successful capture belongs to the requested target. Input confirmation uses
// the capture taken after the click, not WGC presentation-marker age/proofs.
internal static class WgcDomainCaptureAdapter
{
    public static NativeDomainFrame? FromIndependentCapture(CapturedBgraFrame frame, ActionScope scope,
        ClientGeometry geometry, long requestNs, long comparisonNs, WindowBinding captureOwner, long captureScopeEpoch)
    {
        if (captureOwner != scope.Window || frame.Width != geometry.Width || frame.Height != geometry.Height)
            return null;
        return new(scope with { SourceSequence = frame.AcquisitionSequence, CapturedNs = frame.CaptureTimestampNs },
            geometry, frame.Pixels, frame.Stride);
    }
}
