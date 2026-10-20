using System.Text.Json;
using NteHost.DomainActions;
using WgcLiveHarness;

// Regression of the real f-run refusal. Presentation markers are not input
// safety: an image captured for the right window is usable without age/proof gates.
static class InputCaptureChecks
{
    public static void Run()
    {
        using var file = JsonDocument.Parse(File.ReadAllText("tests/fixtures/native-input-future-discard.json"));
        var proof = file.RootElement.GetProperty("frames")[0].Deserialize<CaptureDeliveryProof>(
            new JsonSerializerOptions { PropertyNameCaseInsensitive = true })!;
        var window = new WindowBinding(1, 2, 3, 0);
        var scope = new ActionScope("test", 1, 1, 100, 100, "AUCTION_READY", "", 0,
            window, 0, 1, proof.ReadbackCompletedNs, false, false, true, false, false, false);
        var frame = new CapturedBgraFrame(4, 4, 16, new byte[64], proof.ReadbackCompletedNs,
            "", proof.SourceNs, proof.AcquisitionSequence, proof, CaptureScopeEpoch: proof.PoolEpoch);
        NativeDomainFrame? Adapt(WindowBinding owner) => WgcDomainCaptureAdapter.FromIndependentCapture(frame,
            scope, new(4, 4, 0, 0), proof.RequestNs, proof.ReadbackCompletedNs + 10_000_000_000, owner, proof.PoolEpoch);
        if (Adapt(window) is null) throw new Exception("REAL_CAPTURE_MUST_NOT_BE_REJECTED_FOR_PRESENTATION_MARKER_OR_AGE");
        if (Adapt(window with { Pid = 99 }) is not null) throw new Exception("WRONG_WINDOW");
        Console.WriteLine("PASS actual f-run marker no longer blocks input capture; wrong window rejected; zero input");
    }
    public static void RunFuture() => Run();
}
