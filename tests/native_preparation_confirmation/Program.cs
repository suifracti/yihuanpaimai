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
            null, null, []) { GoldAverageVisible = mode != "no-effect", PurpleCountVisible = mode == "purple-effect" };
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
        int activationArg=Array.IndexOf(args,"--controlled-focus");
        bool gameFocus=args.Contains("--bound-game-focus");
        if(gameFocus) activationArg=Array.IndexOf(args,"--bound-game-focus");
        if(activationArg>=0)
        {
            long hwnd=long.Parse(args[activationArg+1]);
            var name=new System.Text.StringBuilder(256);
            GetClassName(new IntPtr(hwnd),name,name.Capacity);
            Require(name.ToString()==(gameFocus?"UnrealWindow":"NteV22ControlledWindow"),"EXPECTED_WINDOW_CLASS");
            bool ok=false;
            var worker=new Thread(()=>{
                var type=Host.GetType("WgcLiveHarness.TicketedSceneAnchorDispatch+GameFocus",true)!;
                object focus=Activator.CreateInstance(type,true)!;
                type.GetField("Target")!.SetValue(focus,hwnd);
                ok=(bool)type.GetMethod("Activate")!.Invoke(focus,null)!;
                Console.WriteLine(type.GetField("LastActivation")?.GetValue(focus));
            });
            worker.Start(); Require(worker.Join(5000),"ACTIVATION_BOUNDED");
            Require(ok,"WORKER_ACTIVATES_CONTROLLED_WINDOW");
            Console.WriteLine("PASS worker activation, no keys or clicks");return 0;
        }
        var parseAssets=Host.GetType("WgcLiveHarness.SceneAnchorOcr",true)!.GetMethod("ParseAssets")!;
        foreach(var text in new[]{"2 ， 635 490","2 635,490","2,635,490"})
            Require((long?)parseAssets.Invoke(null,new object[]{text})==2635490,"MIXED_THOUSANDS_SEPARATORS");
        foreach(var text in new[]{"0 2,635,490","2,63 490","2 635 49"})
            Require(parseAssets.Invoke(null,new object[]{text}) is null,"INVALID_BALANCE_GROUPS");
        if (args.Contains("--bid-warning-only")) { BidWarningChecks(); return 0; }
        if (args.Contains("--focus-history-only")) { FocusHistory(); return 0; }
        if (args.Contains("--cancelled-guard-only")) { CancelledGuard(); return 0; }
        if (args.Contains("--input-boundary-only")) { InputBoundary(); return 0; }
        int sceneArg = Array.IndexOf(args, "--scene-wait-replay");
        if (sceneArg >= 0) { SceneWaitReplay(args[sceneArg + 1]); return 0; }
        SceneWaitChecks();
        InputBoundary();
        KeypadSequence();
        int stockArg = Array.IndexOf(args, "--stock-replay");
        if (stockArg >= 0) { StockReplay(args[stockArg + 1]); return 0; }
        int imageArg = Array.IndexOf(args, "--saved-image");
        if (imageArg >= 0) { SavedImage(args[imageArg + 1]); return 0; }
        int listArg = Array.IndexOf(args, "--open-list-image");
        if (listArg >= 0) { SavedImage(args[listArg + 1], openList: true); return 0; }
        foreach (string mode in new[] { "slow-effect", "slow-frame", "legacy-unqualified", "no-effect", "pre-click", "wrong-window", "purple-effect", "purple-no-effect" }) Check(mode);
        Console.WriteLine("PASS simple confirmation: one decode per frame, post-click effect, 3s UNKNOWN/no resend, correct window; zero OS input");
        return 0;
    }
    static void BidWarningChecks()
    {
        foreach(var mode in new[]{"success","no-effect","wrong-amount","wrong-window","wrong-round","pre-click","unknown","throws","expired"})
        {
            long now=10_000_000_000;
            var scope=new ActionScope("match",1,1,5_000_000,0,"AUCTION","lease",0,new(1,2,3,0),0,1,now,
                true,true,true,true,false,false) { MatchGeneration=1,ObservationSessionId="test" };
            var intent=new DomainIntent("bid",DomainActionKind.Bid,"match",1,1,1729462,5_000_000,
                now+30_000_000_000,0,"lease",scope.Window) {MatchGeneration=1,ObservationSessionId="test",MaxSafeBid=2_000_000,ApprovalId="test"};
            var port=new SentPort(); var coordinator=new DomainActionCoordinator(()=>scope,()=>now,port);
            var pending=coordinator.Dispatch(intent); Require(pending.Status==ReceiptStatus.SENT_PENDING_CONFIRMATION,"INITIAL_SENT");
            now+=100_000_000;
            var frame=scope with {Scene="BID_WARNING",CapturedNs=now,SourceSequence=2};
            if(mode=="wrong-window") frame=frame with {Window=new(4,2,3,0)};
            if(mode=="wrong-round") frame=frame with {Round=2};
            if(mode=="pre-click") frame=frame with {CapturedNs=pending.SentNs};
            if(mode=="expired") now+=3_000_000_000;
            int clicks=0;
            PortOutcome Click(Func<bool> current) { Require(current(),"CURRENT_WINDOW");clicks++;
                if(mode=="throws") throw new Exception("unknown"); return new(true,mode!="unknown","TEST"); }
            var next=coordinator.ContinueBidWarning("bid",mode=="wrong-amount"?1729463:1729462,frame,Click);
            bool valid=mode is "success" or "no-effect" or "unknown" or "throws";
            Require(clicks==(valid?1:0),"WARNING_CLICK_SCOPE:"+mode);
            coordinator.ContinueBidWarning("bid",mode=="wrong-amount"?1729463:1729462,frame,Click);
            Require(clicks==(valid?1:0),"WARNING_NEVER_RESENT:"+mode);
            Require(port.Sends==1,"SUBMIT_NEVER_RESENT");
            if(mode=="success") {
                now+=50_000_000;
                var proof=new VisibleResult("bid",DomainActionKind.Bid,"match",1,1,1729462,null,"AUCTION_WAITING",3,now,
                    true,scope.Window,0) {OriginMatchGeneration=1,ObservationSessionId="test"};
                Require(coordinator.Confirm(proof).Status==ReceiptStatus.CONFIRMED,"FINAL_VISIBLE_ACCEPTANCE");
            } else {
                now+=4_000_000_000;
                var end=coordinator.Poll() ?? next;
                Require(end?.Status==ReceiptStatus.UNKNOWN,"UNCONFIRMED_STOPS:"+mode);
                coordinator.Dispatch(intent);Require(port.Sends==1,"UNKNOWN_NO_RETRY");
            }
        }
        Console.WriteLine("PASS high-price dialog: exact amount/window/round/post-click, one continuation, confirmed only after own bid, unknown/exception/timeout no resend; zero OS input");
    }
    sealed class SentPort : IRestrictedDomainInputPort
    {
        public int Sends;
        public PortOutcome TrySend(DomainIntent i, Func<bool> current)
        { Require(current(), "DISPATCH_SCOPE"); Sends++; return new(true, true, "FAKE_SENT"); }
    }
    [System.Runtime.InteropServices.DllImport("user32.dll",CharSet=System.Runtime.InteropServices.CharSet.Unicode)]
    static extern int GetClassName(IntPtr hwnd,System.Text.StringBuilder name,int size);
    static void FocusHistory()
    {
        var type=Host.GetType("WgcLiveHarness.TicketedSceneAnchorDispatch+GameFocus",true)!;
        object focus=Activator.CreateInstance(type,true)!;
        type.GetField("Target")!.SetValue(focus,1L);
        var observe=type.GetMethod("ObserveForeground",BindingFlags.NonPublic|BindingFlags.Instance)!;
        FocusSnapshot Read(long foreground)=>(FocusSnapshot)observe.Invoke(focus,new object[]{foreground})!;
        var armed=Read(1); var away=Read(2); var returned=Read(1);
        Require(armed.ForegroundId==armed.TargetId,"INITIAL_TARGET");
        Require(away.ForegroundId!=away.TargetId,"OTHER_FOREGROUND_STILL_REJECTED");
        Require(returned.ForegroundId==returned.TargetId && returned.Epoch==armed.Epoch,
            "RETURNED_GAME_MUST_NOT_INHERIT_IDLE_FOCUS_HISTORY");
        type.GetField("Target")!.SetValue(focus,3L);
        Require(Read(1).TargetId!=armed.TargetId,"CHANGED_TARGET_STILL_DISTINCT");
        Console.WriteLine("PASS current target focus, away/return between actions, changed target; zero capture/input");
    }
    static void CancelledGuard()
    {
        var type=Host.GetType("WgcLiveHarness.TicketedSceneAnchorDispatch",true)!;
        var observer=new FakeInputObserver();
        var raw=new CountingRawInputBackend();
        var guard=new InputSafetyGuard(observer,new FakeFocusSnapshotProvider(),new FakeCursorBackend(),raw);
        observer.Start(_=>{}); Require(guard.Arm(new(1)).Ok,"FAKE_ARM");
        guard.Cancel("ORIGINAL_FAILURE");
        var receipts=new List<System.Text.Json.Nodes.JsonObject>();
        object dispatch=type.GetConstructors(BindingFlags.NonPublic|BindingFlags.Instance).Single().Invoke(
            new object?[]{"test",new Decoder("slow-effect"),guard,null,null,null,null,null,
                (Action<System.Text.Json.Nodes.JsonObject>)receipts.Add});
        type.GetField("armed",BindingFlags.NonPublic|BindingFlags.Instance)!.SetValue(dispatch,true);
        var intent=new DomainIntent("restock",DomainActionKind.OpenToolSetup,"lobby",0,0,null,100,1000000,0,
            "lobby",new(1,2,3,0)){ObservationSessionId="test",MatchGeneration=1,ApprovalId="test"};
        var options=new System.Text.Json.JsonSerializerOptions{PropertyNamingPolicy=System.Text.Json.JsonNamingPolicy.CamelCase};
        options.Converters.Add(new System.Text.Json.Serialization.JsonStringEnumConverter());
        var message=new System.Text.Json.Nodes.JsonObject{["protocolVersion"]=1,["requestId"]="test",
            ["bootId"]="boot",["observationSessionId"]="test",
            ["intent"]=System.Text.Json.JsonSerializer.SerializeToNode(intent,options)};
        var target=new NteHost.WindowMonitor.WindowMonitorSnapshot{TargetHwnd=1,TargetPid=2,
            TargetIdentity=new(1,2,"fake","fake","fake",true,3)};
        type.GetMethod("TryHandle")!.Invoke(dispatch,new object?[]{message,"boot",target,null,
            (Func<DomainIntent,NativeDomainFrame?>)(_=>throw new Exception("MUST_NOT_CAPTURE")),
            (Action<System.Text.Json.Nodes.JsonObject>)receipts.Add});
        Require(receipts.Count==1 && (string?)receipts[0]["type"]=="domain.action.dispatch.rejected"
            && (string?)receipts[0]["reason"]=="INPUT_GUARD_Cancelled:ORIGINAL_FAILURE", "KEEP_FIRST_REASON_AND_STOP");
        Require(raw.SendCallCount==0,"NO_INPUT_OR_REARM");observer.Stop();
        Console.WriteLine("PASS cancelled guard rejects once with original reason before focus, capture or input");
    }
    static bool SceneExpired(string scene, long nowMs, ref object?[] state)
    {
        var args=new object?[]{scene,state[0],state[1],nowMs};
        bool expired=(bool)Host.GetType("WgcLiveHarness.NativeObservationService",true)!
            .GetMethod("UnknownSceneExpired",BindingFlags.NonPublic|BindingFlags.Static)!.Invoke(null,args)!;
        state=new[]{args[1],args[2]};
        return expired;
    }
    static void SceneWaitReplay(string path)
    {
        object?[] state={null,null};
        int rows=0;
        foreach(string line in File.ReadLines(path)) {
            using var row=System.Text.Json.JsonDocument.Parse(line);
            var r=row.RootElement;
            string scene=r.GetProperty("scene").GetString()!;
            long now=r.GetProperty("captureTimestampNs").GetInt64()/1_000_000;
            Require(!SceneExpired(scene,now,ref state),"REAL_LOADING_ABORT_AT_FRAME_"+r.GetProperty("frameSequence"));
            rows++;
        }
        Console.WriteLine($"PASS real scene sequence: {rows} frames, loading does not end observation; no capture/input");
    }
    static void SceneWaitChecks()
    {
        object?[] state={null,null};
        Require(!SceneExpired("AUCTION_LOADING",0,ref state),"LOADING");
        Require(!SceneExpired("UNKNOWN",100,ref state) && !SceneExpired("UNKNOWN",120000,ref state),"LOADING_HAS_NO_TOTAL_TIMEOUT");
        Require(!SceneExpired("IN_AUCTION",120001,ref state),"KNOWN_RECOVERS");
        Require(!SceneExpired("UNKNOWN",120100,ref state) && SceneExpired("UNKNOWN",130100,ref state),"UNKNOWN_DURING_AUCTION_STILL_TIMES_OUT");
        Require(!SceneExpired("AUCTION_LOBBY",130101,ref state) && !SceneExpired("UNKNOWN",130102,ref state),"KNOWN_RESETS_UNKNOWN_TIMER");
        Console.WriteLine("PASS loading wait and ordinary unknown-scene timeout remain distinct");
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
        Require(Display("250.04K").MatchesAmount(250038)
            && Display("250.04K").MatchesAmount(250035)
            && !Display("250.04K").MatchesAmount(250034),"K_HALF_DISPLAY_UNIT_5");
        Require(Display("1.25M").MatchesAmount(1255000)
            && !Display("1.25M").MatchesAmount(1255001),"M_HALF_DISPLAY_UNIT_5000");
        Require(Display("359.1K").MatchesAmount(359100)
            && !Display("359.1K").MatchesAmount(359106),"HIDDEN_ZERO_RETAINS_HUNDREDTH_PRECISION");
        Require(Display("203,930").MatchesAmount(203930),"EXACT_INTEGER_RETAINED");
        Require(!Display("203.92K").MatchesAmount(203930)
            && !Display("允许出价范围203.93K").MatchesAmount(203930)
            && !Display("203.93K 1").MatchesAmount(203930),"WRONG_OR_UNBOUND_DISPLAY_REJECTED");
        Console.WriteLine("PASS keypad: one clear and exact bounded digits, including repeated digits (no input)");
    }
    static void InputBoundary()
    {
        var type=Host.GetType("WgcLiveHarness.TicketedSceneAnchorDispatch",true)!;
        foreach(int sending in new[]{0,1})
        foreach(var origin in Enum.GetValues<InputEventOrigin>())
        foreach(var kind in Enum.GetValues<InputEventKind>()) {
            var observer=new FakeInputObserver();
            var trace=new InMemoryInputTraceSink();
            var raw=new CountingRawInputBackend();
            var guard=new InputSafetyGuard(observer,new FakeFocusSnapshotProvider(),new FakeCursorBackend(),raw,trace);
            object host=type.GetConstructors(BindingFlags.Instance|BindingFlags.NonPublic).Single().Invoke(
                new object?[]{"test",new Decoder("slow-effect"),guard,null,null,null,null,null,(Action<System.Text.Json.Nodes.JsonObject>)(_=>{})});
            observer.Start(_=>{});
            Require(guard.Arm(new(1)).Ok,"FAKE_ARM");
            type.GetField("dispatching",BindingFlags.Instance|BindingFlags.NonPublic)!.SetValue(host,sending);
            uint flags=origin==InputEventOrigin.Hardware?0u:kind==InputEventKind.KeyDown?0x10u:0x1u;
            if(origin==InputEventOrigin.LowerIntegrityInjected) flags|=0x2u;
            type.GetMethod("OnObservedInput",BindingFlags.Instance|BindingFlags.NonPublic)!.Invoke(host,new object[]{
                new ObservedInputEvent(kind,kind==InputEventKind.KeyDown?InputDeviceClass.Keyboard:InputDeviceClass.Mouse,
                    origin,0,10,20,TraceClock.NowNs(),1) { NativeFlags=flags }});
            bool human=sending==1 && origin==InputEventOrigin.Hardware;
            Require(guard.State==(human?GuardState.Cancelled:GuardState.Armed)
                && guard.UserTakeoverSeen==human,"ONLY_PHYSICAL_INPUT_TAKES_OVER:"+sending+":"+origin+":"+kind);
            if(sending==1 && origin!=InputEventOrigin.Hardware)
                Require(trace.Contains("OBSERVED_INJECTED_NOT_HUMAN") && guard.SelfExemptionCount==0,
                    "FOREIGN_INJECTION_RECORDED_NOT_SELF_EXEMPTED_OR_HUMAN");
            Require(raw.SendCallCount==0,"OBSERVER_NEVER_RESENDS_INPUT");
            observer.Stop();
        }
        Console.WriteLine("PASS 30 input boundaries: idle input allowed, only hardware takes over sending, injected input is recorded separately; zero OS input");
    }
    static void StockReplay(string replay)
    {
        var decoder = SceneAnchorGameDecoder.Load("assets/scene_anchors");
        decoder.ReadAmount=(SceneAnchorGameDecoder.AmountSample)Host.GetType("WgcLiveHarness.SceneAnchorOcr",true)!
            .GetMethod("ReadAmountField")!.CreateDelegate(typeof(SceneAnchorGameDecoder.AmountSample));
        decoder.ReadCommittedText=(SceneAnchorGameDecoder.TextSample)Host.GetType("WgcLiveHarness.SceneAnchorOcr",true)!
            .GetMethod("ReadCommittedText")!.CreateDelegate(typeof(SceneAnchorGameDecoder.TextSample));
        decoder.ReadIntelText=(SceneAnchorGameDecoder.TextSample)Host.GetType("WgcLiveHarness.SceneAnchorOcr",true)!
            .GetMethod("ReadText")!.CreateDelegate(typeof(SceneAnchorGameDecoder.TextSample));
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
            Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(new {path=row.GetProperty("path").GetString(),v?.Scene,v?.Instruments,v?.AmountField,v?.BidWarningAmount,controls=v?.Controls.Select(x=>x.Primitive.ToString())}));
            if(row.TryGetProperty("expectedWarningAmount",out var warning)) {
                Console.WriteLine("WARNING_TEXT="+Host.GetType("WgcLiveHarness.SceneAnchorOcr",true)!.GetMethod("ReadText")!
                    .Invoke(null,new object[]{(ReadOnlyMemory<byte>)pixels,w,h,w*4,540,505,840,70}));
                Require(v?.BidWarningAmount==warning.GetInt64(),"REAL_WARNING_EXACT_AMOUNT");
                var captured=new NativeDomainFrame(scope,new(w,h,0,0),pixels,w*4);
                var evidence=new CapturedDomainControlEvidence(()=>captured,decoder);
                var intent=new DomainIntent("warning",DomainActionKind.Bid,scope.MatchId,0,0,warning.GetInt64(),5000000,
                    long.MaxValue,0,"test",scope.Window) {MatchGeneration=1,ObservationSessionId="test"};
                Require(evidence.Locate(DomainPrimitive.ConfirmBidWarning,intent) is not null,"REAL_WARNING_CONTROL");
                Require(evidence.Locate(DomainPrimitive.ConfirmBidWarning,intent with {Amount=1729463}) is null,"WRONG_DIALOG_AMOUNT_REJECTED");
                Require(v?.OwnBid is null,"DIALOG_IS_NOT_ACCEPTED_BID");
            }
            if(row.TryGetProperty("expectedAmount",out var expectedAmount)) {
                var region=v?.Controls.Single(c=>c.Primitive==DomainPrimitive.FocusAmountField);
                Console.WriteLine($"FILLED_ROI={region?.Left},{region?.Top},{region?.Width},{region?.Height}");
                if(region is not null) {
                    var ocr=Host.GetType("WgcLiveHarness.SceneAnchorOcr",true)!;
                    object[] crop={(ReadOnlyMemory<byte>)pixels,w,h,w*4,region.Left,region.Top,region.Width,region.Height};
                    Console.WriteLine("FILLED_TEXT="+ocr.GetMethod("ReadText")!.Invoke(null,crop));
                    Console.WriteLine("FILLED_LATIN_ENLARGED="+ocr.GetMethod("ReadCommittedText")!.Invoke(null,crop));
                }
                Require(v?.AmountField==expectedAmount.GetInt64(),"REAL_FILLED_AMOUNT_MUST_READ_EXACTLY");
            }
            if(v?.Scene=="TOOL_SETUP") {
                var read=Host.GetType("WgcLiveHarness.SceneAnchorOcr",true)!.GetMethod("ReadText")!;
                foreach(var box in new[]{new[]{320,235,115,55},new[]{421,927,145,66}})
                    Console.WriteLine("OCR "+read.Invoke(null,new object[]{(ReadOnlyMemory<byte>)pixels,w,h,w*4,box[0],box[1],box[2],box[3]}));
            }
            Require(v?.Scene==row.GetProperty("scene").GetString(),"STOCK_SCENE");
            if(row.TryGetProperty("expectedRefillCost",out var expectedCost))
            {
                Console.WriteLine("ENTRY_FEE_OCR="+Host.GetType("WgcLiveHarness.SceneAnchorOcr",true)!.GetMethod("ReadText")!
                    .Invoke(null,new object[]{(ReadOnlyMemory<byte>)pixels,w,h,w*4,620,500,690,90}));
                Require(v?.Instruments?.RefillCost==expectedCost.GetInt64(),"REAL_ENTRY_FEE_READ");
            }
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
            mode == "saved-open" ? "AUCTION_READY" : mode.StartsWith("purple-") ? "INSTRUMENT_PURPLE_SELECTED" : "INSTRUMENT_GOLD_SELECTED", "lease",
            now + 8_000_000_000, window, 0, 1, now, true, true, true, true, false, false)
            { MatchGeneration = 1, ObservationSessionId = "test", ApprovalId = "test" };
        var intent = new DomainIntent("use", mode == "saved-open" ? DomainActionKind.OpenInstrument : mode.StartsWith("purple-") ? DomainActionKind.UsePurpleCount : DomainActionKind.UseGoldAverage, "match", 1, 1, null, 100,
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
        Require(mode is "slow-effect" or "slow-frame" or "legacy-unqualified" or "saved-effect" or "saved-open" or "purple-effect" ? status == "CONFIRMED" && decodes == 1
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
