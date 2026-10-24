using NteHost.DomainActions;

static class SettlementSaleChecks
{
    static void Check(bool ok,string reason) { if(!ok) throw new Exception(reason); }
    sealed class Backend(bool red, bool cancel=true) : ITicketedDomainBackend
    {
        public bool[] Selected=[false,true,true,true,true,red];
        public List<DomainPrimitive> Calls=[];
        public PortOutcome Execute(DomainPrimitive p,DomainIntent i,Func<bool> current) {
            Calls.Add(p); int index=Array.IndexOf(SettlementSale.Toggles,p);
            if(index>=0 && (index!=5 || cancel)) Selected[index]=!Selected[index];
            return new(true,true,"SENT");
        }
        public AmountFieldReadback? ReadAmountField()=>null;
        public SettlementSale? ReadSaleSelection()=>new(Selected.ToArray());
    }
    sealed class Decoder(SettlementSale sale) : IGameDomainFrameDecoder
    {
        public DecodedDomainFrame Decode(NativeDomainFrame f)=>new("SETTLEMENT",f.Scope.Round,
            f.Scope.MatchId,f.Scope.MatchGeneration,null,null,[]) { Sale=sale };
    }
    public static void Run(string pixelsPath)
    {
        var fixture=new Fixture();
        fixture.Scope=fixture.Scope with { Scene="SETTLEMENT", SettlementArchived=true };
        var intent=fixture.Intent("sale-1",DomainActionKind.SellNonRed) with { SettlementAcquired=true, FundsBefore=200000 };
        var backend=new Backend(true);
        var result=new RestrictedDomainInputPort(backend,()=>fixture.Now).TrySend(intent,()=>true);
        Check(result.Completed && backend.Calls.SequenceEqual(new[]{DomainPrimitive.SaleRed,DomainPrimitive.SaleWhite,DomainPrimitive.SellNonRed}),"RED_FIRST_AND_ALL_NON_RED");
        backend=new Backend(true,false);
        result=new RestrictedDomainInputPort(backend,()=>fixture.Now).TrySend(intent,()=>true);
        Check(!result.Completed && result.Reason=="SALE_RED_NOT_CANCELLED" && !backend.Calls.Contains(DomainPrimitive.SellNonRed),"RED_BLOCKS_SALE");
        Check(fixture.Coordinator.Dispatch(intent with { SettlementAcquired=false }).Status==ReceiptStatus.NOT_SENT,"OTHER_WINNER_REJECTED");
        var pending=fixture.Coordinator.Dispatch(intent);
        Check(pending.Status==ReceiptStatus.SENT_PENDING_CONFIRMATION,"SALE_SENT");
        fixture.Now+=4_000_000_000;
        Check(fixture.Coordinator.Poll()?.Status==ReceiptStatus.UNKNOWN,"SALE_UNKNOWN");
        Check(fixture.Coordinator.Dispatch(intent with {IntentId="sale-2"}).Status==ReceiptStatus.SENT_PENDING_CONFIRMATION,"SALE_RETRY_ALLOWED");

        var raw=File.ReadAllBytes(pixelsPath);
        var frame=new NativeDomainFrame(fixture.Scope with {CapturedNs=fixture.Now+1,SourceSequence=11},new(1920,1080,0,0),raw,1920*4);
        var actual=SettlementSale.Read(frame);
        Check(actual?.Ready==true,"REAL_C02_FIRST_FIVE_ON_RED_OFF");
        var decoder=SceneAnchorGameDecoder.Load("assets/scene_anchors");
        var decoded=frame.DecodeOnce(decoder);
        Check(decoded?.Scene=="SETTLEMENT" && decoded.Sale?.Ready==true && decoded.Controls.Count(c=>c.Primitive==DomainPrimitive.SellNonRed)==1,"REAL_SALE_CONTROL");
        var evidence=new CapturedDomainControlEvidence(()=>frame,decoder);
        Check(evidence.Locate(DomainPrimitive.SellNonRed,intent)!=null,"REAL_PRE_SEND_C02");
        var redDecoder=new Decoder(new([true,true,true,true,true,true]));
        Check(new CapturedDomainControlEvidence(()=>frame,redDecoder).Locate(DomainPrimitive.SellNonRed,intent)==null,"FINAL_FRAME_RED_REJECTED");

        var pending2=pending with {SentNs=fixture.Now};
        foreach(var row in new[]{(new SettlementSale([true,true,true,true,true,false],200000,false),false),
            (new SettlementSale([true,true,true,true,true,false],200001,false),true),
            (new SettlementSale([true,true,true,true,true,false],null,true),true)}) {
            var producer=new NativeVisibleResultProducer(new Decoder(row.Item1),()=>fixture.Now+2);
            Check((producer.FromCapture(intent,pending2,frame,null)!=null)==row.Item2,"SOLD_OR_CREDIT_ONLY");
        }
        var wrong=frame.Scope with {Window=new(99,20,30,40)};
        Check(new NativeVisibleResultProducer(new Decoder(actual!),()=>fixture.Now+2).FromCapture(intent,pending2,
            new(wrong,frame.Geometry,raw,1920*4),null)==null,"FOREIGN_WINDOW_REJECTED");
        Console.WriteLine("PASS sale: C02 real frame/control; red cancellation and refusal; own winner; retry; sold/credit confirmation; target identity");
    }
}
