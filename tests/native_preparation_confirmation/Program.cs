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
sealed class CountedDecoder(IGameDomainFrameDecoder inner) : IGameDomainFrameDecoder
{
    public int Reads;
    public DecodedDomainFrame? Decode(NativeDomainFrame f) { Reads++; return inner.Decode(f); }
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
        InputBoundary();
        int stockArg = Array.IndexOf(args, "--stock-replay");
        if (stockArg >= 0) { StockReplay(args[stockArg + 1]); return 0; }
        int imageArg = Array.IndexOf(args, "--saved-image");
        if (imageArg >= 0) { SavedImage(args[imageArg + 1]); return 0; }
        int listArg = Array.IndexOf(args, "--open-list-image");
        if (listArg >= 0) { SavedImage(args[listArg + 1], openList: true); return 0; }
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
    static void InputBoundary()
    {
        var type=Host.GetType("WgcLiveHarness.TicketedSceneAnchorDispatch",true)!;
        foreach(int sending in new[]{0,1}) {
            var observer=new FakeInputObserver();
            var guard=new InputSafetyGuard(observer,new FakeFocusSnapshotProvider(),new FakeCursorBackend(),new CountingRawInputBackend());
            object host=type.GetConstructors(BindingFlags.Instance|BindingFlags.NonPublic).Single().Invoke(
                new object?[]{"test",new Decoder("slow-effect"),guard,null,null,null,null,null,(Action<System.Text.Json.Nodes.JsonObject>)(_=>{})});
            observer.Start(_=>{});
            Require(guard.Arm(new(1)).Ok,"FAKE_ARM");
            type.GetField("dispatching",BindingFlags.Instance|BindingFlags.NonPublic)!.SetValue(host,sending);
            type.GetMethod("OnObservedInput",BindingFlags.Instance|BindingFlags.NonPublic)!.Invoke(host,new object[]{
                new ObservedInputEvent(InputEventKind.MouseButtonDown,InputDeviceClass.Mouse,InputEventOrigin.Hardware,0,10,20,TraceClock.NowNs(),1)});
            Require(guard.State==(sending==0?GuardState.Armed:GuardState.Cancelled),"IDLE_ENTRY_VS_ACTIVE_TAKEOVER");
            observer.Stop();
        }
        Console.WriteLine("PASS manual entry between actions does not disable later tickets; input during a transaction cancels (fake only)");
    }
    static void StockReplay(string replay)
    {
        var decoder = SceneAnchorGameDecoder.Load("assets/scene_anchors");
        var readStock = Host.GetType("WgcLiveHarness.SceneAnchorOcr", true)!.GetMethod("ReadInstruments")!
            .CreateDelegate<Func<NativeDomainFrame, string, int, InstrumentStock?>>();
        decoder.ReadInstruments = (frame, scene, top) => { Console.WriteLine("GROUP_TOP="+top); return readStock(frame,scene,top); };
        using var doc = System.Text.Json.JsonDocument.Parse(File.ReadAllText(replay));
        foreach (var row in doc.RootElement.EnumerateArray())
        {
            var raw = File.ReadAllBytes(row.GetProperty("path").GetString()!);
            int w = BitConverter.ToInt32(raw,18), sh=BitConverter.ToInt32(raw,22), h=Math.Abs(sh), offset=BitConverter.ToInt32(raw,10);
            var pixels = new byte[w*h*4];
            for(int y=0;y<h;y++) Buffer.BlockCopy(raw,offset+(sh<0?y:h-1-y)*w*4,pixels,y*w*4,w*4);
            var scope = new ActionScope("lobby-test",0,0,1000000,0,"LOBBY","lobby",0,new(1,2,3,0),0,1,1,true,true,true,true,false,false)
                {MatchGeneration=1,ObservationSessionId="test"};
            var v=decoder.Decode(new(scope,new(w,h,0,0),pixels,w*4));
            Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(new {path=row.GetProperty("path").GetString(),v?.Scene,v?.Instruments,controls=v?.Controls.Select(x=>x.Primitive.ToString())}));
            if(v?.Scene=="TOOL_SETUP") {
                var read=Host.GetType("WgcLiveHarness.SceneAnchorOcr",true)!.GetMethod("ReadText")!;
                foreach(var box in new[]{new[]{320,235,115,55},new[]{421,927,145,66}})
                    Console.WriteLine("OCR "+read.Invoke(null,new object[]{(ReadOnlyMemory<byte>)pixels,w,h,w*4,box[0],box[1],box[2],box[3]}));
            }
            Require(v?.Scene==row.GetProperty("scene").GetString(),"STOCK_SCENE");
            if(row.TryGetProperty("replaceAnchor",out var replace) && replace.GetBoolean()) {
                var frame=new NativeDomainFrame(scope,new(w,h,0,0),pixels,w*4);
                var intent=new DomainIntent("bind-only",DomainActionKind.Bid,scope.MatchId,scope.Round,0,442779,
                    1000000,long.MaxValue,0,"lobby",scope.Window) {MatchGeneration=1,ObservationSessionId="test"};
                var controls=new CapturedDomainControlEvidence(()=>frame,decoder);
                Require(controls.Locate(DomainPrimitive.ReplaceAmountDigits,intent) is not null,"REAL_KEYPAD_REPLACE_ANCHOR_MISSING");
                Console.WriteLine("PASS saved real keypad supplies the replace primitive anchor; no input sent");
            }
            if(row.TryGetProperty("gold",out var g)) Require(v?.Instruments?.GoldAverage==g.GetInt32(),"GOLD_STOCK");
            if(row.TryGetProperty("cost",out var c)) Require(v?.Instruments?.RefillCost==c.GetInt64(),"REFILL_COST");
            if(row.TryGetProperty("refillFundsBefore",out var before)) {
                var current=scope with { Scene="TOOL_REFILL_CONFIRM", CapturedNs=TraceClock.NowNs(),
                    LeaseExpiresNs=TraceClock.NowNs()+8_000_000_000,ApprovalId="test" };
                var port=new SentPort();
                var coordinator=new DomainActionCoordinator(()=>current,TraceClock.NowNs,port);
                var intent=new DomainIntent("real-refill",DomainActionKind.ConfirmToolRefill,current.MatchId,
                    0,0,5000,1000000,TraceClock.NowNs()+8_000_000_000,0,"lobby",current.Window)
                    { MatchGeneration=1,ObservationSessionId="test",MinimumFunds=100000,FundsBefore=before.GetInt64(),ApprovalId="test" };
                var pending=coordinator.Dispatch(intent);
                Require(pending.Status==ReceiptStatus.SENT_PENDING_CONFIRMATION,"REPLAY_REFILL_PENDING");
                var frame=new NativeDomainFrame(scope with {CapturedNs=TraceClock.NowNs(),SourceSequence=2},new(w,h,0,0),pixels,w*4);
                var producer=new NativeVisibleResultProducer(decoder,TraceClock.NowNs);
                var effect=producer.FromCapture(intent,pending,frame,null);
                Require(effect is not null && coordinator.Confirm(effect).Status==ReceiptStatus.CONFIRMED,"REAL_LOBBY_DEBIT_CONFIRMS_REFILL");
                Require(port.Sends==1,"NO_REFILL_REPLAY");
                Console.WriteLine("PASS saved real lobby debit + decoder/OCR + producer/coordinator; fake send, stock still reread before entry");
            }
        }
    }
    static void SavedImage(string path, bool openList = false)
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
        decoder.ReadCommittedAmount = (p, w, h, stride, x, y, rw, rh) => {
            return read(p, w, h, stride, x, y, rw, rh);
        };
        var counted = new CountedDecoder(decoder);
        Check(openList ? "saved-open" : "saved-effect", counted, pixels, width, height, () => counted.Reads);
        Console.WriteLine("PASS real saved pixels + production decoder/OCR/Host Observe; fixture scope and fake send, not real capture qualification");
    }
    static void Check(string mode, IGameDomainFrameDecoder? saved = null, byte[]? pixels = null,
        int width = 4, int height = 4, Func<int>? readCount = null)
    {
        var type = Host.GetType("WgcLiveHarness.TicketedSceneAnchorDispatch", true)!;
        long now = TraceClock.NowNs();
        var window = new WindowBinding(1, 2, 3, 0);
        var scope = new ActionScope("match", 1, 1, 100, 100,
            mode == "saved-open" ? "AUCTION_READY" : "INSTRUMENT_GOLD_SELECTED", "lease",
            now + 8_000_000_000, window, 0, 1, now, true, true, true, true, false, false)
            { MatchGeneration = 1, ObservationSessionId = "test", ApprovalId = "test" };
        var intent = new DomainIntent("use", mode == "saved-open" ? DomainActionKind.OpenInstrument : DomainActionKind.UseGoldAverage, "match", 1, 1, null, 100,
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
        Require(mode is "slow-effect" or "slow-frame" or "legacy-unqualified" or "saved-effect" or "saved-open" ? status == "CONFIRMED" && decodes == 1
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
