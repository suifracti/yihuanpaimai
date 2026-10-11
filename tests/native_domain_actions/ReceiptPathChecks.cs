using NteHost.DomainActions;
using WgcLiveHarness;

static class ReceiptPathChecks
{
    sealed class Decoder : IGameDomainFrameDecoder
    {
        public bool TypedOnly, OtherSeat, CachedSeat;
        public DecodedDomainFrame Decode(NativeDomainFrame f) => new("AUCTION", f.Scope.Round,
            f.Scope.MatchId, f.Scope.MatchGeneration,
            new(OtherSeat ? 2 : 1, "self", 500, !TypedOnly, CachedSeat ? "old-frame" : f.EvidenceRef), 500, []);
    }
    static void Require(bool ok, string why) { if (!ok) throw new Exception(why); }
    public static void Run()
    {
        var f = new Fixture(); var i = f.Intent(); var receipt = f.Coordinator.Dispatch(i);
        f.Now += 10_000_000;
        f.Scope = f.Scope with { SourceSequence = 11, CapturedNs = f.Now };
        var pixels = new byte[4 * 4 * 4]; var geometry = new ClientGeometry(4, 4, 0, 0);
        var good = new NativeDomainFrame(f.Scope, geometry, pixels, 16);
        var decoder = new Decoder(); var producer = new NativeVisibleResultProducer(decoder, () => f.Now);
        Require(producer.FromCapture(i, receipt, good, new(1, "self")) != null, "OWN_FRESH_PRODUCER");
        foreach (var bad in new[] {
            f.Scope with { SourceQualified = false }, f.Scope with { CapturedNs = f.Now + 1 },
            f.Scope with { CapturedNs = receipt.SentNs }, f.Scope with { Round = 2 },
            f.Scope with { MatchId = "other" }, f.Scope with { MatchGeneration = 2 },
            f.Scope with { ObservationSessionId = "other" },
            f.Scope with { Window = f.Scope.Window with { ProcessInstanceToken = 99 } },
            f.Scope with { TakeoverGeneration = 3 } })
            Require(producer.FromCapture(i, receipt, new(bad, geometry, pixels, 16), new(1, "self")) == null, "INVALID_CAPTURE_PRODUCER");
        decoder.TypedOnly = true; Require(producer.FromCapture(i, receipt, good, new(1, "self")) == null, "TYPED_NOT_ACCEPTED");
        decoder.TypedOnly = false; decoder.OtherSeat = true; Require(producer.FromCapture(i, receipt, good, new(1, "self")) == null, "OPPONENT_NOT_SELF");
        decoder.OtherSeat = false; decoder.CachedSeat = true; Require(producer.FromCapture(i, receipt, good, new(1, "self")) == null, "CACHED_SEAT_NOT_FRESH");
        Require(new CapturedDomainControlEvidence(() => good, new UnconnectedGameDomainDecoder()).Locate(DomainPrimitive.SubmitBid, i) == null, "UNKNOWN_GAME_ANCHOR_NOT_CONNECTED");
        Console.WriteLine("PASS independent capture receipts: qualification/future/stale/cross-match/window/takeover/typed/other/cached seat");
        var wgc = new CapturedBgraFrame(4, 4, 16, pixels, f.Now - 1, "", f.Now - 2, 11) { CaptureScopeEpoch = 1 };
        NativeDomainFrame? Convert(CapturedBgraFrame frame, ActionScope scope) =>
            WgcDomainCaptureAdapter.FromIndependentCapture(frame, scope, geometry, f.Now - 3, f.Now, i.Window, 1);
        Require(Convert(wgc, f.Scope) != null, "STRICT_WGC_BRIDGE");
        foreach (var bad in new[] { wgc with { SourceTimestampNs = f.Now + 1 },
            wgc with { CaptureTimestampNs = f.Now + 1 }, wgc with { SourceTimestampNs = f.Now - 4 },
            wgc with { CaptureScopeEpoch = 2 }, wgc with { AcquisitionSequence = 0 }, wgc with { Width = 5 } })
            Require(Convert(bad, f.Scope) == null, "WGC_BOUNDARY_GATE");
        Require(Convert(wgc, f.Scope with { Window = i.Window with { Hwnd = 99 } }) == null, "FOREIGN_CAPTURE_OWNER");
        Require(Convert(wgc, f.Scope with { SourceQualified = false }) == null, "SOURCE_GATE_PRESERVED");
        Console.WriteLine("PASS concrete WGC bridge: strict request/source/readback/owner/epoch/geometry gates");
    }
}
