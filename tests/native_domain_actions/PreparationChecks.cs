using System.Diagnostics;
using System.Text.Json;
using NteHost.DomainActions;

// Real pixels may be replayed; scope/clock are test fixtures. Never discovers
// windows or constructs a real input backend.
static class PreparationChecks
{
    static void Require(bool yes, string reason) { if (!yes) throw new Exception(reason); }
    public static void Run(string? replayPath)
    {
        var kinds = new[] { DomainActionKind.OpenInstrument, DomainActionKind.SelectGoldAverage,
            DomainActionKind.UseGoldAverage, DomainActionKind.OpenBidPanel };
        foreach (var kind in kinds)
        {
            var f = new Fixture();
            f.Scope = f.Scope with { Scene = AuctionPreparation.ExpectedScene(kind)! };
            var intent = f.Intent("prepare-" + kind, kind);
            Require(f.Coordinator.Dispatch(intent).Status == ReceiptStatus.SENT_PENDING_CONFIRMATION, "PREPARATION_DISPATCH:" + kind);
            Require(f.Coordinator.Dispatch(intent).Status == ReceiptStatus.SENT_PENDING_CONFIRMATION && f.Port.Sends == 1, "PREPARATION_REPLAY");
            Require(f.Coordinator.Confirm(f.Evidence(intent, "UNRELATED")).Status == ReceiptStatus.SENT_PENDING_CONFIRMATION, "UNRELATED_CONFIRMED");
            string next = kind switch { DomainActionKind.OpenInstrument => "INSTRUMENT_LIST",
                DomainActionKind.SelectGoldAverage => "INSTRUMENT_GOLD_SELECTED",
                DomainActionKind.UseGoldAverage => "AUCTION_READY", _ => "AUCTION" };
            if (kind == DomainActionKind.UseGoldAverage)
                Require(f.Coordinator.Confirm(f.Evidence(intent, next)).Status == ReceiptStatus.SENT_PENDING_CONFIRMATION, "PANEL_CLOSE_IS_NOT_USE_PROOF");
            Require(f.Coordinator.Confirm(f.Evidence(intent, next) with { PreparationEffectVisible = true }).Status == ReceiptStatus.CONFIRMED, "INDEPENDENT_EFFECT_REQUIRED");
            foreach (var change in new Func<ActionScope, ActionScope>[] {
                s => s with { ForegroundMatches = false },
                s => s with { Window = s.Window with { Pid = 999 } } })
            {
                var bad = new Fixture();
                bad.Scope = bad.Scope with { Scene = AuctionPreparation.ExpectedScene(kind)! };
                var i = bad.Intent("bad-" + kind, kind);
                bad.Scope = change(bad.Scope);
                Require(bad.Coordinator.Dispatch(i).Status == ReceiptStatus.NOT_SENT && bad.Port.Sends == 0, "PREPARATION_GUARD:" + kind);
            }
            var backend = new FakeTicketBackend();
            var closed = new RestrictedDomainInputPort(backend, () => f.Now);
            Require(closed.TrySend(intent, () => true).Completed && backend.Operations.Count == 1
                && backend.Operations[0].ToString() == kind.ToString(), "ONLY_NAMED_PRIMITIVE");
        }
        Console.WriteLine("PASS preparation policy and named ticket primitives (fake input only)");
        foreach(var kind in new[] {DomainActionKind.OpenToolSetup,DomainActionKind.RequestToolRefill,
            DomainActionKind.ConfirmToolRefill,DomainActionKind.CloseToolSetup})
        {
            var f=new Fixture();
            f.Scope=f.Scope with {Round=0,Scene=AuctionPreparation.ExpectedScene(kind)!};
            var intent=f.Intent("lobby-"+kind,kind) with {Round=0,Amount=kind==DomainActionKind.ConfirmToolRefill?500:null,
                MinimumFunds=100000,GoldStockBefore=0};
            Require(f.Coordinator.Dispatch(intent).Status==ReceiptStatus.SENT_PENDING_CONFIRMATION,"LOBBY_DISPATCH:"+kind);
            string next=kind switch {DomainActionKind.RequestToolRefill=>"TOOL_REFILL_CONFIRM",DomainActionKind.CloseToolSetup=>"LOBBY",_=>"TOOL_SETUP"};
            var evidence=f.Evidence(intent,next) with {Instruments=new(1,1,0,200000)};
            if(kind==DomainActionKind.ConfirmToolRefill)
                Require(f.Coordinator.Confirm(evidence with {Instruments=new(0,0,500,200000)}).Status==ReceiptStatus.SENT_PENDING_CONFIRMATION,"REFILL_MUST_HAVE_VISIBLE_STOCK_EFFECT");
            Require(f.Coordinator.Confirm(evidence).Status==ReceiptStatus.CONFIRMED,"LOBBY_CONFIRM:"+kind);
            f.Coordinator.Dispatch(intent);
            Require(f.Port.Sends==1,"LOBBY_ONE_SHOT");
        }
        var bidFixture = new Fixture();
        var bid = bidFixture.Intent();
        Require(bidFixture.Coordinator.Dispatch(bid).Status == ReceiptStatus.SENT_PENDING_CONFIRMATION, "BID_PENDING");
        Require(bidFixture.Coordinator.Confirm(bidFixture.Evidence(bid, "AUCTION_READY")).Status == ReceiptStatus.CONFIRMED,
            "CLOSED_PANEL_STILL_CONFIRMS_OWN_BID");
        var listDecoder = SceneAnchorGameDecoder.Load("assets/scene_anchors");
        Require(listDecoder.TryGetTemplate("instrument_list_title.png", out var title), "LIST_TITLE_TEMPLATE");
        var listPixels = new byte[1920 * 1080 * 4];
        SceneAnchorGameDecoder.PaintGray(listPixels, 1920 * 4, 70, 140, title);
        var list = listDecoder.Decode(new NativeDomainFrame(new Fixture().Scope,
            new(1920, 1080, 0, 0), listPixels, 1920 * 4));
        Require(list?.Scene == "INSTRUMENT_LIST" && list.Controls.Count == 0 && !list.GoldAverageVisible,
            "OPEN_LIST_DOES_NOT_REQUIRE_OR_INVENT_GOLD_TOOL");
        Console.WriteLine("PASS list title confirms open panel without inventing an absent instrument (synthetic pixels)");
        if (replayPath is null || !File.Exists(replayPath)) return;
        using var doc = JsonDocument.Parse(File.ReadAllText(replayPath));
        var root = doc.RootElement;
        var decoder = SceneAnchorGameDecoder.Load(root.GetProperty("anchors").GetString()!);
        Require(decoder.Ready, "REAL_REPLAY_CATALOG");
        var output = new List<object>();
        foreach (var row in root.GetProperty("frames").EnumerateArray())
        {
            var path = row.GetProperty("path").GetString()!;
            var bytes = File.ReadAllBytes(path);
            int width = BitConverter.ToInt32(bytes, 18), signedHeight = BitConverter.ToInt32(bytes, 22);
            int height = Math.Abs(signedHeight), offset = BitConverter.ToInt32(bytes, 10);
            Require(BitConverter.ToInt16(bytes, 28) == 32, "BGRA_BMP_REQUIRED");
            var pixels = new byte[width * height * 4];
            for (int y = 0; y < height; y++)
                Buffer.BlockCopy(bytes, offset + (signedHeight < 0 ? y : height - 1 - y) * width * 4,
                    pixels, y * width * 4, width * 4);
            var scope = new Fixture().Scope with { SourceQualified = false };
            var frame = new NativeDomainFrame(scope, new(width, height, 0, 0), pixels, width * 4);
            var timer = Stopwatch.StartNew();
            var view = decoder.Decode(frame);
            timer.Stop();
            var expected = row.GetProperty("expected").GetString();
            Require(view?.Scene == expected, "REAL_SCENE:" + path + ":" + view?.Scene + " expected " + expected);
            if (row.TryGetProperty("goldAverageVisible", out var goldExpected))
                Require(view!.GoldAverageVisible == goldExpected.GetBoolean(), "REAL_GOLD_EFFECT:" + path);
            Require(view!.Controls.All(a => !a.SourceQualified), "PLANNING_MUST_NOT_GRANT_INPUT");
            var names = view.Controls.Select(a => a.Primitive.ToString()).ToArray();
            if (row.TryGetProperty("absentControls", out var absent))
                foreach (var control in absent.EnumerateArray())
                    Require(!names.Contains(control.GetString()), "ABSENT_CONTROL_PUBLISHED:" + control.GetString());
            output.Add(new { path, expected, actual = view.Scene, controls = names, view.GoldAverageVisible, elapsedMs = timer.Elapsed.TotalMilliseconds, inputQualified = false });
            Console.WriteLine($"PASS real saved scene {Path.GetFileName(path)} {view.Scene} {timer.ElapsedMilliseconds}ms");
        }
        File.WriteAllText(root.GetProperty("output").GetString()!, JsonSerializer.Serialize(output, new JsonSerializerOptions { WriteIndented = true }));
    }
}
