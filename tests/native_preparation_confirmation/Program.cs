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
        KeypadSequence();
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
    static void KeypadSequence()
    {
        var keys=WindowsTicketedDomainBackend.KeypadSequence(343268);
        Require(keys.SequenceEqual(new[]{DomainPrimitive.ClearAmount,
            DomainPrimitive.AmountDigit3,DomainPrimitive.AmountDigit4,DomainPrimitive.AmountDigit3,
            DomainPrimitive.AmountDigit2,DomainPrimitive.AmountDigit6,DomainPrimitive.AmountDigit8}),"EXACT_DIGITS_ONCE");
        Require(WindowsTicketedDomainBackend.KeypadSequence(0).Count==0,"BOUNDED_AMOUNT");
        CapturedOwnBid Display(string text) => new(0,"own",null,true,"test") {DisplayText=text};
        Require(Display("203.93K").MatchesAmount(203930),"COMPACT_K");
        Require(Display("203 ． 93K").MatchesAmount(203930),"REAL_WINDOWS_OCR_FULLWIDTH_DOT");
        Require(Display("343.27K").MatchesAmount(343268),"DISPLAY_PRECISION_NOT_FABRICATED_EXACT_OCR");
        Require(Display("393.54K").MatchesAmount(393545)
            && !Display("393.54K").MatchesAmount(393546),"REAL_HALF_STEP_AND_OUTSIDE_DISPLAY_PRECISION");
        Require(Display("393 · 54K").MatchesAmount(393545),"REAL_ENLARGED_WINDOWS_OCR_DECIMAL_MARK");
        Require(Display("1.25M").MatchesAmount(1250000),"COMPACT_M");
        Require(Display("203,930").MatchesAmount(203930),"EXACT_INTEGER_RETAINED");
        Require(!Display("203.92K").MatchesAmount(203930)
            && !Display("允许出价范围203.93K").MatchesAmount(203930)
            && !Display("203.93K 1").MatchesAmount(203930),"WRONG_OR_UNBOUND_DISPLAY_REJECTED");
        Console.WriteLine("PASS keypad: one clear and exact bounded digits, including repeated digits (no input)");
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
        decoder.ReadAmount=(SceneAnchorGameDecoder.AmountSample)Host.GetType("WgcLiveHarness.SceneAnchorOcr",true)!
            .GetMethod("Read")!.CreateDelegate(typeof(SceneAnchorGameDecoder.AmountSample));
        decoder.ReadCommittedText=(SceneAnchorGameDecoder.TextSample)Host.GetType("WgcLiveHarness.SceneAnchorOcr",true)!
            .GetMethod("ReadCommittedText")!.CreateDelegate(typeof(SceneAnchorGameDecoder.TextSample));
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
            Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(new {path=row.GetProperty("path").GetString(),v?.Scene,v?.Instruments,v?.AmountField,controls=v?.Controls.Select(x=>x.Primitive.ToString())}));
            if(row.TryGetProperty("expectedAmount",out var expectedAmount)) {
                var region=v?.Controls.Single(c=>c.Primitive==DomainPrimitive.FocusAmountField);
                Console.WriteLine($"FILLED_ROI={region?.Left},{region?.Top},{region?.Width},{region?.Height}");
                Require(v?.AmountField==expectedAmount.GetInt64(),"REAL_FILLED_AMOUNT_MUST_READ_EXACTLY");
            }
            if(v?.Scene=="TOOL_SETUP") {
                var read=Host.GetType("WgcLiveHarness.SceneAnchorOcr",true)!.GetMethod("ReadText")!;
                foreach(var box in new[]{new[]{320,235,115,55},new[]{421,927,145,66}})
                    Console.WriteLine("OCR "+read.Invoke(null,new object[]{(ReadOnlyMemory<byte>)pixels,w,h,w*4,box[0],box[1],box[2],box[3]}));
            }
            Require(v?.Scene==row.GetProperty("scene").GetString(),"STOCK_SCENE");
            if(row.TryGetProperty("expectedFunds",out var expectedFunds)) {
                var readText=Host.GetType("WgcLiveHarness.SceneAnchorOcr",true)!.GetMethod("ReadText")!;
                if(v?.Scene=="LOBBY") Console.WriteLine("ACTUAL_ASSETS_TEXT="+readText.Invoke(null,new object[]{
                    (ReadOnlyMemory<byte>)pixels,w,h,w*4,1340,20,170,65}));
                Console.WriteLine("ASSETS_ENLARGED_TEXT="+Host.GetType("WgcLiveHarness.SceneAnchorOcr",true)!
                    .GetMethod("ReadAssetsText")!.Invoke(null,new object[]{(ReadOnlyMemory<byte>)pixels,w,h,w*4,v!.Scene}));
                var amount=Host.GetType("WgcLiveHarness.SceneAnchorOcr",true)!.GetMethod("ReadAssets")!
                    .Invoke(null,new object[]{(ReadOnlyMemory<byte>)pixels,w,h,w*4,v!.Scene});
                Require((long?)amount==expectedFunds.GetInt64(),"REAL_SCENE_FUNDS_READ");
            }
            if(row.TryGetProperty("expectedCommitted",out var expectedCommitted)) {
                bool Matches(long amount) => v?.OwnBid?.MatchesAmount(amount)==true;
                Console.WriteLine("ACTUAL_COMMITTED_TEXT="+v?.OwnBid?.DisplayText);
                Require(Matches(expectedCommitted.GetInt64()),"REAL_COMMITTED_COMPACT_BID_NOT_READ");
                Require(!Matches(expectedCommitted.GetInt64()+100),"WRONG_COMPACT_AMOUNT_REJECTED");
                var current=scope with {Round=1,Scene="AUCTION",CapturedNs=TraceClock.NowNs(),
                    LeaseExpiresNs=TraceClock.NowNs()+8_000_000_000,ApprovalId="test"};
                var port=new SentPort();
                var coordinator=new DomainActionCoordinator(()=>current,TraceClock.NowNs,port);
                var intent=new DomainIntent("real-committed",DomainActionKind.Bid,current.MatchId,1,0,
                    expectedCommitted.GetInt64(),1000000,TraceClock.NowNs()+8_000_000_000,0,"lobby",current.Window)
                    {MatchGeneration=1,ObservationSessionId="test",MaxSafeBid=1000000,ApprovalId="test"};
                var pending=coordinator.Dispatch(intent);
                Require(pending.Status==ReceiptStatus.SENT_PENDING_CONFIRMATION,"COMMITTED_REPLAY_PENDING");
                var frame=new NativeDomainFrame(current with {CapturedNs=TraceClock.NowNs(),SourceSequence=2},new(w,h,0,0),pixels,w*4);
                var producer=new NativeVisibleResultProducer(decoder,TraceClock.NowNs);
                var result=producer.FromCapture(intent,pending,frame,new(0,SceneAnchorGameDecoder.OwnCommittedBidIdentity));
                Require(result is not null && coordinator.Confirm(result).Status==ReceiptStatus.CONFIRMED,"REAL_COMPACT_RESULT_CONFIRMS");
                Require(port.Sends==1,"NO_BID_RESEND");
                Console.WriteLine("PASS saved actual submitted compact bid matches only its displayed value; no input");
            }
            if(row.TryGetProperty("replaceAnchor",out var replace) && replace.GetBoolean()) {
                var frame=new NativeDomainFrame(scope,new(w,h,0,0),pixels,w*4);
                var intent=new DomainIntent("bind-only",DomainActionKind.Bid,scope.MatchId,scope.Round,0,442779,
                    1000000,long.MaxValue,0,"lobby",scope.Window) {MatchGeneration=1,ObservationSessionId="test"};
                var controls=new CapturedDomainControlEvidence(()=>frame,decoder);
                Require(controls.Locate(DomainPrimitive.ReplaceAmountDigits,intent) is not null,"REAL_KEYPAD_REPLACE_ANCHOR_MISSING");
                Console.WriteLine("PASS saved real keypad supplies the replace primitive anchor; no input sent");
            }
            if(row.TryGetProperty("keypad",out var keypad) && keypad.GetBoolean()) {
                Require(v is not null && v.AmountField is null,"EMPTY_KEYPAD_IS_NOT_A_BID_AMOUNT");
                foreach(string name in new[]{"ClearAmount","AmountDigit0","AmountDigit1","AmountDigit2","AmountDigit3",
                    "AmountDigit4","AmountDigit5","AmountDigit6","AmountDigit7","AmountDigit8","AmountDigit9"}) {
                    Require(Enum.TryParse<DomainPrimitive>(name,out var key)
                        && v!.Controls.Count(c=>c.Primitive==key)==1,"REAL_KEYPAD_KEY_MISSING:"+name);
                }
                var field=v!.Controls.Single(c=>c.Primitive==DomainPrimitive.FocusAmountField);
                Console.WriteLine($"AMOUNT_ROI={field.Left},{field.Top},{field.Width},{field.Height}");
                Require(field.Width>=250,"READ_COMPLETE_AMOUNT_LINE");
                Console.WriteLine("PASS real empty keypad: named clear/digits and amount-only region; no OS input");
            }
            if(row.TryGetProperty("hoverAfterClear",out var hoverPath)) {
                var hover=File.ReadAllBytes(hoverPath.GetString()!);
                int ho=BitConverter.ToInt32(hover,10), hh=BitConverter.ToInt32(hover,22);
                var hoverPixels=new byte[w*h*4];
                for(int y=0;y<h;y++) Buffer.BlockCopy(hover,ho+(hh<0?y:h-1-y)*w*4,hoverPixels,y*w*4,w*4);
                var initialKeypad=new NativeDomainFrame(scope,new(w,h,0,0),pixels,w*4);
                var after=new NativeDomainFrame(scope with {SourceSequence=2,CapturedNs=2},new(w,h,0,0),hoverPixels,w*4);
                int captures=0;
                IDomainControlEvidence evidence=new CapturedDomainControlEvidence(()=>++captures==1?initialKeypad:after,decoder);
                var intent=new DomainIntent("real-hover",DomainActionKind.Bid,scope.MatchId,scope.Round,0,222809,
                    1000000,long.MaxValue,0,"lobby",scope.Window) {MatchGeneration=1,ObservationSessionId="test"};
                Require(evidence.Locate(DomainPrimitive.ReplaceAmountDigits,intent) is not null,"INITIAL_PANEL");
                var keypadControls=evidence.AmountKeypad;
                evidence.CaptureAmountField(); // independently read the real pink hover frame
                Require(keypadControls.Count==11 && evidence.AmountKeypad==keypadControls,"HOVER_MUST_NOT_INVALIDATE_KEYPAD_LAYOUT");
                var clicks=WindowsTicketedDomainBackend.KeypadSequence(222809);
                Require(clicks.All(key=>keypadControls.Count(c=>c.Primitive==key)==1)
                    && clicks.Count==7 && captures==2,"ONE_LAYOUT_NOT_REDETECTED_PER_DIGIT");
                Console.WriteLine("PASS real white-to-pink Clear hover keeps one bound keypad layout; no OS input");
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
