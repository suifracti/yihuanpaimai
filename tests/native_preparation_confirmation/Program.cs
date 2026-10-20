using System.Reflection;
using System.Runtime.Loader;
using NteHost.DomainActions;
using NteHost.Input;

// Exercises the actual Host Observe path with a slow fake decoder. No window,
// hook, capture device, cursor backend or raw input backend is constructed.
// Reflection only instantiates the existing private Host wiring without its OS
// factory. Synthetic pixels/effect/latency test plumbing, not visual accuracy.
sealed class Decoder(string mode) : IGameDomainFrameDecoder
{
    public int Reads;
    public DecodedDomainFrame? Decode(NativeDomainFrame f)
    {
        Reads++; Thread.Sleep(150);
        return new("AUCTION_READY", f.Scope.Round, f.Scope.MatchId, f.Scope.MatchGeneration,
            null, null, []) { GoldAverageVisible = mode != "no-effect" };
    }
}
static class Program
{
    static void Require(bool ok, string why) { if (!ok) throw new Exception(why); }
    static Assembly Host = null!;
    sealed class ReplayHostContext : AssemblyLoadContext
    {
        protected override Assembly? Load(AssemblyName name) => name.Name?.StartsWith("NteHost.") == true
            ? Default.LoadFromAssemblyName(name) : null;
    }
    static int Main(string[] args)
    {
        int hostArg = Array.IndexOf(args, "--host");
        Host = hostArg >= 0 ? new ReplayHostContext().LoadFromAssemblyPath(Path.GetFullPath(args[hostArg + 1]))
            : Assembly.Load("WgcLiveHarness");
        Console.WriteLine("Host assembly: " + Host.Location);
        int imageArg = Array.IndexOf(args, "--saved-image");
        if (imageArg >= 0) { SavedImage(args[imageArg + 1]); return 0; }
        foreach (string mode in new[] { "slow-effect", "slow-frame", "legacy-unqualified", "no-effect", "pre-click", "wrong-window" }) Check(mode);
        Console.WriteLine("PASS simple confirmation: one decode per frame, post-click effect, 3s UNKNOWN/no resend, correct window; zero OS input");
        return 0;
    }
    sealed class SentPort : IRestrictedDomainInputPort
    {
        public int Sends;
        public PortOutcome TrySend(DomainIntent i, Func<bool> current)
        { Require(current(), "DISPATCH_SCOPE"); Sends++; return new(true, true, "FAKE_SENT"); }
    }
    static void SavedImage(string path)
    {
        var bytes = File.ReadAllBytes(path);
        int width = BitConverter.ToInt32(bytes, 18), signedHeight = BitConverter.ToInt32(bytes, 22);
        int height = Math.Abs(signedHeight), offset = BitConverter.ToInt32(bytes, 10);
        Require(BitConverter.ToInt16(bytes, 28) == 32, "BGRA_BMP");
        var pixels = new byte[width * height * 4];
        for (int y = 0; y < height; y++) Buffer.BlockCopy(bytes,
            offset + (signedHeight < 0 ? y : height - 1 - y) * width * 4, pixels, y * width * 4, width * 4);
        var decoder = SceneAnchorGameDecoder.Load("assets/scene_anchors");
        var read = (SceneAnchorGameDecoder.AmountSample)Host.GetType("WgcLiveHarness.SceneAnchorOcr", true)!
            .GetMethod("Read")!.CreateDelegate(typeof(SceneAnchorGameDecoder.AmountSample));
        // Main has already used this OCR engine for lobby funds before an
        // instrument can be sent. Warm that model before starting frame age.
        read(pixels, width, height, width * 4, 0, 0, 8, 8);
        int reads = 0;
        decoder.ReadCommittedAmount = (p, w, h, stride, x, y, rw, rh) => {
            reads++; return read(p, w, h, stride, x, y, rw, rh);
        };
        Check("saved-effect", decoder, pixels, width, height, () => reads);
        Console.WriteLine("PASS real saved pixels + production decoder/OCR/Host Observe; fixture scope and fake send, not real capture qualification");
    }
    static void Check(string mode, IGameDomainFrameDecoder? saved = null, byte[]? pixels = null,
        int width = 4, int height = 4, Func<int>? readCount = null)
    {
        var type = Host.GetType("WgcLiveHarness.TicketedSceneAnchorDispatch", true)!;
        long now = TraceClock.NowNs();
        var window = new WindowBinding(1, 2, 3, 0);
        var scope = new ActionScope("match", 1, 1, 100, 100, "INSTRUMENT_GOLD_SELECTED", "lease",
            now + 8_000_000_000, window, 0, 1, now, true, true, true, true, false, false)
            { MatchGeneration = 1, ObservationSessionId = "test", ApprovalId = "test" };
        var intent = new DomainIntent("use", DomainActionKind.UseGoldAverage, "match", 1, 1, null, 100,
            now + 8_000_000_000, 0, "lease", window)
            { MatchGeneration = 1, ObservationSessionId = "test", ApprovalId = "test" };
        var synthetic = new Decoder(mode);
        var decoder = saved ?? synthetic;
        var receipts = new List<System.Text.Json.Nodes.JsonObject>();
        object? host = null;
        bool observing = false;
        var capture = type.GetMethod("CaptureEngine", BindingFlags.Instance | BindingFlags.NonPublic)!;
        var port = new SentPort();
        var coordinator = new DomainActionCoordinator(() => observing
            ? ((NativeDomainFrame?)capture.Invoke(host, null))?.Scope : scope, TraceClock.NowNs, port);
        var runtime = new NativeDomainActionRuntime(coordinator, new(decoder, TraceClock.NowNs), null, receipts.Add);
        host = type.GetConstructors(BindingFlags.NonPublic | BindingFlags.Instance).Single().Invoke(
            new object?[] { "test", decoder, null, null, null, null, null, runtime,
                (Action<System.Text.Json.Nodes.JsonObject>)receipts.Add });
        Require(runtime.Dispatch(intent).Status == ReceiptStatus.SENT_PENDING_CONFIRMATION, "PENDING");
        type.GetField("pending", BindingFlags.NonPublic | BindingFlags.Instance)!.SetValue(host, intent);
        var fresh = scope with { SourceSequence = 2, Scene = "AUCTION_READY",
            SourceQualified = mode != "legacy-unqualified", CapturedNs = mode == "pre-click" ? now - 1 : TraceClock.NowNs(),
            Window = mode == "wrong-window" ? window with { Pid = 99 } : window };
        var frame = new NativeDomainFrame(fresh, new(width, height, 0, 0), pixels ?? new byte[64], width * 4);
        if (mode == "slow-frame") Thread.Sleep(650);
        observing = true;
        type.GetMethod("Observe")!.Invoke(host, new object[] { frame });
        var status = (string?)receipts.Last()["receipt"]?["status"];
        int decodes = readCount?.Invoke() ?? synthetic.Reads;
        Console.WriteLine($"{mode}: status={status} decodes={decodes} fakeSends={port.Sends} ageMs={(TraceClock.NowNs() - fresh.CapturedNs) / 1_000_000.0:F1}");
        Require(port.Sends == 1, "NO_RESEND");
        Require(mode is "slow-effect" or "slow-frame" or "legacy-unqualified" or "saved-effect" ? status == "CONFIRMED" && decodes == 1
            : status != "CONFIRMED", "CONFIRM_ONLY_FRESH_MATCHED_EFFECT");
        if (decodes > 0) {
            frame.DecodeOnce(decoder);
            Require((readCount?.Invoke() ?? synthetic.Reads) == decodes, "ONE_DECODE_PER_FRAME");
        }
        if (mode == "no-effect")
        {
            Thread.Sleep(3100);
            Require(runtime.Poll()?.Status == ReceiptStatus.UNKNOWN, "THREE_SECOND_TIMEOUT");
            Require(runtime.Dispatch(intent with { IntentId = "retry" }).Status == ReceiptStatus.NOT_SENT
                && port.Sends == 1, "UNKNOWN_NEVER_RESENDS");
        }
    }
}
