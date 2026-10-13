using System.Text.Json.Nodes;
using WgcLiveHarness;

internal static class SkipAnimationChecks
{
    public static void Run(string root, Func<long, long, CaptureDeliveryProof> fixture)
    {
        Directory.CreateDirectory(root);
        var events = new List<JsonObject>();
        long now = 100_000_000_000;
        var target = new JsonObject { ["targetHwnd"] = 123L, ["targetPid"] = 456,
            ["processInstanceToken"] = 789L };
        var context = new WarehouseSourceContext("record", target, "map", 16, 9, true, true,
            long.MaxValue, 1);
        DeliveryVisualSummary? latest = null;
        var platform = new SkipPlatform();
        using var lease = new WarehouseEvidenceLease(root, "offline", events.Add, () => now,
            scrollDown: (_, _) => false, capturePolicy: "wgc-delivery-v1", latestSummary: () => latest,
            skipAnimation: (c, current) => WarehouseWindowScroll.SendSkipAnimation(c, current, platform: platform));
        lease.UpdateContext(context);
        JsonObject Command(string operation, int ordinal = 0) => new() {
            ["type"] = WarehouseEvidenceLease.ControlType, ["schemaVersion"] = WarehouseEvidenceLease.SchemaV2,
            ["operation"] = operation, ["commandId"] = Guid.NewGuid().ToString("N"), ["nonce"] = "n"+ordinal,
            ["observationSessionId"] = "offline", ["reviewSessionId"] = "review", ["reviewGeneration"] = 1,
            ["recordStableKey"] = "record", ["matchGeneration"] = 1L, ["expectedTargetInstance"] = target.DeepClone(),
            ["leaseToken"] = lease.LeaseToken, ["requestOrdinal"] = ordinal, ["remainingPages"] = 100,
            ["remainingPngBytes"] = 64L*1024*1024, ["pngEncoding"] = WarehouseEvidenceLease.PngEncoding,
            ["allowWindowScroll"] = true, ["retainIndependentOriginals"] = true, ["captureFirst"] = true,
            ["allowSkipAnimation"] = true };
        lease.Handle(Command("OPEN"));
        Check((bool?)events.Last()["details"]?["skipAnimationSupported"] == true, "skip capability negotiated");
        JsonObject Save(int sequence)
        {
            lease.Handle(Command("REQUEST_PAGE", sequence));
            var gate = lease.PendingRequestGateNs!.Value;
            var proof = fixture(sequence, gate);
            now = proof.ReadbackCompletedNs + 1;
            latest = new(proof.CaptureId, 1, proof.ReadbackCompletedNs, "scene", "warehouse", true)
                { SkipButtonBgr = Enumerable.Repeat((byte)220, 30).ToArray() };
            Check(lease.TryPublish(new(16, 9, 64, Enumerable.Repeat((byte)sequence, 576).ToArray(),
                proof.SourceNs, proof.ReadbackCompletedNs, "offline", sequence, "", sequence, proof,
                latest, gate, 1), () => true), "independent source saved");
            var source = (JsonObject)events.Last()["source"]!.DeepClone();
            var ack = Command("ACK_SOURCE", sequence);
            foreach (var key in new[] { "sourceLeaseId", "pixelSha256", "bmpSha256" }) ack[key] = source[key]!.DeepClone();
            ack["result"] = "SAVED";
            lease.Handle(ack);
            var click = Command("SKIP_ANIMATION", sequence);
            click["sourceLeaseId"] = source["sourceLeaseId"]!.DeepClone();
            click["pixelSha256"] = source["pixelSha256"]!.DeepClone();
            click["savedCaptureId"] = proof.CaptureId;
            return click;
        }
        var first = Save(1);
        platform.Timeout = true;
        lease.Handle(first);
        Check(lease.IsOpen && (string?)events.Last()["details"]?["classification"] == "UNKNOWN",
            "unknown skip outcome keeps collection available");
        var sends = platform.Down;
        lease.Handle(first);
        Check(platform.Down == sends, "same image is consumed; no blind replay");
        var second = Save(2);
        platform.Timeout = false;
        // Inventory/reveal pixels may change; they cannot prohibit the skip control.
        latest = latest! with { WarehouseRoiSha256 = "changed", ScrollContentRoiSha256 = "changed" };
        lease.Handle(second);
        Check(lease.IsOpen && platform.Down == sends + 1
            && (string?)events.Last()["details"]?["classification"] == "SENT", "fresh image permits retry after unknown");
        var third = Save(3);
        latest = latest! with { SkipButtonBgr = Enumerable.Repeat((byte)60, 30).ToArray() };
        lease.Handle(third);
        Check(platform.Down == sends + 1 && lease.IsOpen
            && (string?)events.Last()["details"]?["classification"] == "NOT_SENT", "disabled button is not clicked");
        var fourth = Save(4);
        latest = latest! with { SceneRoiSha256 = "other" };
        lease.Handle(fourth);
        Check(!lease.IsOpen && platform.Down == sends + 1, "changed scene stops input");
        var attempt = new WarehouseScrollAttempt();
        platform.Target = platform.Target with { Pid = 999 };
        Check(!WarehouseWindowScroll.SendSkipAnimation(context with { ScrollAttempt = attempt }, () => true,
            platform: platform) && !attempt.SendInterfaceInvoked, "wrong window never receives a click");
        Console.WriteLine("SKIP_ANIMATION_CHECKS_PASS");
    }
    private static void Check(bool condition, string rule)
    { if (!condition) throw new Exception(rule); Console.WriteLine("PASS: " + rule); }
    private sealed class SkipPlatform : WarehouseWindowScroll.IPlatform
    {
        public WarehouseWindowScroll.TargetState Target = new(456,789,"HTGame.exe","UnrealWindow",true,false,true,16,9);
        public bool Timeout;
        public int Down;
        public WarehouseWindowScroll.TargetState ReadTarget(long hwnd) => Target;
        public WarehouseWindowScroll.ScreenPoint ToScreen(long hwnd,int x,int y) => throw new Exception("skip uses client coordinates");
        public WarehouseWindowScroll.SendResult Send(long hwnd,uint wheel,uint coordinates) => throw new Exception("skip is not wheel input");
        public WarehouseWindowScroll.SendResult MovePointer(long hwnd,uint coordinates) => new(1,0,0);
        public WarehouseWindowScroll.SendResult SendButton(long hwnd,bool down,uint coordinates)
        { if (down) Down++; return new(Timeout ? 0 : 1,0,0); }
    }
}
