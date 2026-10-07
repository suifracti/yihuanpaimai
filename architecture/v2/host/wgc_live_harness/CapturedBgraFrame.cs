namespace WgcLiveHarness;

internal sealed record CapturedBgraFrame(
    int Width,
    int Height,
    int Stride,
    byte[] Pixels,
    long CaptureTimestampNs,
    string CapturedAtUtc,
    long SourceTimestampNs, long AcquisitionSequence = 0, CaptureDeliveryProof? DeliveryProof = null, string? DeliveryDiagnosticJson = null);

