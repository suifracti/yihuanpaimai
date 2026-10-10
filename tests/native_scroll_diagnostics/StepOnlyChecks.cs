using System.Text.Json.Nodes;
using WgcLiveHarness;

static class StepOnlyChecks
{
    static void Check(bool value, string reason) { if (!value) throw new Exception(reason); }
    public static void Run(string root, Func<long,long,CaptureDeliveryProof> makeProof)
    {
        var target = new JsonObject { ["targetHwnd"]=123L,["targetPid"]=456,["processInstanceToken"]=789L,["generation"]=1L };
        var c = new WarehouseSourceContext("record",target,"map",4,3,true,true,long.MaxValue,1);
        foreach (var delta in new[] {-120,-1080,-1440,0,120,-121,-1560}) {
            long now=5_000_000_000; var events=new List<JsonObject>(); var platform=new Platform();
            DeliveryVisualSummary? latest=null;
            using var lease=new WarehouseEvidenceLease(Path.Combine(root,delta.ToString()),"offline",events.Add,()=>now,
                scrollDown:(context,current)=>WarehouseWindowScroll.SendDown(context,current,platform:platform),
                capturePolicy:CapturePolicy.Delivery,latestSummary:()=>latest);
            lease.UpdateContext(c);
            JsonObject Command(string op,int n=1)=>new() {
                ["type"]=WarehouseEvidenceLease.ControlType,["schemaVersion"]=WarehouseEvidenceLease.SchemaV2,
                ["operation"]=op,["commandId"]=Guid.NewGuid().ToString("N"),["nonce"]="n"+n,
                ["observationSessionId"]="offline",["reviewSessionId"]="review",["reviewGeneration"]=1,
                ["recordStableKey"]="record",["expectedTargetInstance"]=target.DeepClone(),["matchGeneration"]=1L,
                ["leaseToken"]=lease.LeaseToken,["remainingPages"]=16,["remainingPngBytes"]=64L*1024*1024,
                ["pngEncoding"]=WarehouseEvidenceLease.PngEncoding,["requestOrdinal"]=n,["allowWindowScroll"]=true };
            lease.Handle(Command("OPEN"));
            var saved=new List<JsonObject>(); var proofs=new List<CaptureDeliveryProof>();
            for(var seq=1;seq<=2;seq++) {
                lease.Handle(Command("REQUEST_PAGE",seq)); var gate=lease.PendingRequestGateNs!.Value;
                var p=makeProof(seq,gate); proofs.Add(p); now=p.ReadbackCompletedNs+100;
                latest=new(p.CaptureId,1,p.ReadbackCompletedNs,"scene","warehouse",true,ScrollContentRoiSha256:"content");
                Check(lease.TryPublish(new(4,3,16,Enumerable.Repeat((byte)seq,48).ToArray(),p.SourceNs,p.ReadbackCompletedNs,
                    "2026-10-09T00:00:00Z",seq,"",seq,p,latest,gate,1),()=>true),"source admission");
                var source=(JsonObject)events.Last()["source"]!; saved.Add((JsonObject)source.DeepClone());
                var ack=Command("ACK_SOURCE",seq);
                foreach(var key in new[]{"sourceLeaseId","pixelSha256","bmpSha256"})ack[key]=source[key]!.DeepClone();
                ack["result"]="SAVED"; lease.Handle(ack); now+=500_000_000;
            }
            var scroll=Command("SCROLL_DOWN",2);
            foreach(var key in new[]{"sourceLeaseId","pixelSha256"})scroll[key]=saved[1][key]!.DeepClone();
            scroll["savedCaptureId"]=proofs[0].CaptureId;scroll["stableCaptureId"]=proofs[1].CaptureId;
            scroll["wheelDelta"]=delta; lease.Handle(scroll);
            var valid=delta is -120 or -1080 or -1440;
            Check(platform.Sends==(valid?1:0),"bounded delta send "+delta);
            if(valid) {
                Check(platform.Delta==delta,"actual WM_MOUSEWHEEL encoding");
                var receipt=events.Last();
                Check((string?)receipt["event"]=="SCROLLED" && (int?)receipt["details"]?["delta"]==delta,"exact delta receipt");
            }
        }
        // The scheduler receives a single volatile ROI, not another retained SOURCE.
        long hintNow=8_000_000_000; var hints=new List<JsonObject>();
        var box=DeliveryVisualSummary.ScrollContentBox(1920,1080);
        var hintSummary=new DeliveryVisualSummary("offline/1/1",1,hintNow,"scene","warehouse",true,
            ScrollContentBgr:new byte[(box.Right-box.Left)*(box.Bottom-box.Top)*3]);
        using var hintLease=new WarehouseEvidenceLease(Path.Combine(root,"hint"),"offline",hints.Add,()=>hintNow,
            scrollDown:(_,_)=>throw new Exception("hint must never send"),capturePolicy:CapturePolicy.Delivery,
            latestSummary:()=>hintSummary);
        hintLease.UpdateContext(c with { Width=1920,Height=1080 });
        hintLease.Handle(new JsonObject { ["type"]=WarehouseEvidenceLease.ControlType,["schemaVersion"]=WarehouseEvidenceLease.SchemaV2,
            ["operation"]="OPEN",["commandId"]="open",["nonce"]="n",["observationSessionId"]="offline",["reviewSessionId"]="review",
            ["reviewGeneration"]=1,["recordStableKey"]="record",["expectedTargetInstance"]=target.DeepClone(),["matchGeneration"]=1L,
            ["remainingPages"]=16,["remainingPngBytes"]=64L*1024*1024,["pngEncoding"]=WarehouseEvidenceLease.PngEncoding,
            ["requestOrdinal"]=1,["allowWindowScroll"]=true });
        hintLease.Tick(); hintLease.Tick();
        Check(hints.Count(e=>(string?)e["event"]=="CONTENT_HINT")==1,"same observation is not repeated");
        var hint=hints.Last(); Check((bool?)hint["inputActions"]==false && (bool?)hint["details"]?["sourceAuthority"]==false,"hint has no action authority");
        hintNow+=700_000_000; hintSummary=hintSummary with { CaptureId="offline/1/2",ReadbackNs=hintNow };
        hintLease.Tick();
        Check(Directory.GetFiles(Path.Combine(root,"hint","warehouse-sources"),"*.bmp").Length==1,"one bounded overwritten ROI slot");
        hintLease.Close("STOP"); hintNow+=700_000_000; hintLease.Tick();
        Check(hints.Count(e=>(string?)e["event"]=="CONTENT_HINT")==2,"closed lease cannot emit more hints");
        Console.WriteLine("STEP_AND_HINT_CONTRACTS_PASS");
    }
    sealed class Platform:WarehouseWindowScroll.IPlatform {
        public int Sends,Delta;
        public WarehouseWindowScroll.TargetState ReadTarget(long hwnd)=>new(456,789,"HTGame.exe","UnrealWindow",true,false,true,4,3);
        public WarehouseWindowScroll.ScreenPoint ToScreen(long hwnd,int x,int y)=>new(true,100,100);
        public WarehouseWindowScroll.SendResult Send(long hwnd,uint wheel,uint coordinates) { Sends++;Delta=unchecked((short)(wheel>>16));return new(1,0,0); }
    }
}
