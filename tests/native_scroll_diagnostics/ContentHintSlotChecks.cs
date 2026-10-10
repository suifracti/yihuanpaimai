using System.Security.Cryptography;
using System.Text.Json.Nodes;
using WgcLiveHarness;

// Actual file replacement under a Windows reader lock; no WGC or window send.
static class ContentHintSlotChecks
{
    public static void Run(string root, Func<long, long, CaptureDeliveryProof> fixture)
    {
        void Check(bool ok, string name) { if (!ok) throw new Exception(name); Console.WriteLine("PASS: " + name); }
        long now = 100_000_000_000;
        var events = new List<JsonObject>();
        var target = new JsonObject { ["targetHwnd"] = 123L };
        var pixels = new byte[1920 * 1080 * 4];
        DeliveryVisualSummary? latest = null;
        using var lease = new WarehouseEvidenceLease(root, "offline", events.Add, () => now,
            capturePolicy: CapturePolicy.Delivery, latestSummary: () => latest);
        lease.UpdateContext(new("record", target, "map", 1920, 1080, true, true, now + 70_000_000_000, 1));
        JsonObject Command(string op, int ordinal) => new() {
            ["type"] = WarehouseEvidenceLease.ControlType, ["schemaVersion"] = WarehouseEvidenceLease.SchemaV2,
            ["operation"] = op, ["commandId"] = Guid.NewGuid().ToString("N"), ["nonce"] = "n" + ordinal,
            ["observationSessionId"] = "offline", ["reviewSessionId"] = "review", ["reviewGeneration"] = 1,
            ["recordStableKey"] = "record", ["expectedTargetInstance"] = target.DeepClone(), ["matchGeneration"] = 1L,
            ["leaseToken"] = lease.LeaseToken, ["requestOrdinal"] = ordinal, ["remainingPages"] = 16,
            ["remainingPngBytes"] = 64L * 1024 * 1024, ["pngEncoding"] = WarehouseEvidenceLease.PngEncoding,
            ["allowWindowScroll"] = true, ["retainIndependentOriginals"] = true };
        void Next(long sequence) {
            var proof = fixture(sequence, now + 700_000_000);
            now = proof.ReadbackCompletedNs + 1;
            pixels[(250 * 1920 + 1400) * 4] = (byte)sequence;
            latest = DeliveryVisualSummary.From(new(1920, 1080, 7680, pixels, now,
                "offline", proof.SourceNs, sequence, proof));
        }
        lease.Handle(Command("OPEN", 0));
        var deadline = events.Single(e => (string?)e["event"] == "OPENED")["details"]!["deadlineNs"]!.GetValue<long>();
        Next(1); lease.Tick();
        var initial = events.Last(e => (string?)e["event"] == "CONTENT_HINT");
        var path = initial["details"]!["path"]!.GetValue<string>();
        var initialBytes = File.ReadAllBytes(path);
        using (var reader = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read)) {
            Next(2); lease.Tick();
            var skipped = events.Last(e => (string?)e["event"] == "CONTENT_HINT_SKIPPED");
            Check((string?)skipped["details"]!["publicationStage"] == "replace-slot"
                && (string?)skipped["details"]!["exceptionType"] == "UnauthorizedAccessException",
                "retained reader reproduces this real Windows access-denied failure");
            Check(lease.IsOpen && !events.Any(e => (string?)e["event"] == "CLOSED"),
                "non-authoritative hint collision preserves SOURCE lease");
            Check(File.ReadAllBytes(path).SequenceEqual(initialBytes), "held slot is unchanged");
        }
        Next(3); lease.Tick();
        var recovered = events.Last(e => (string?)e["event"] == "CONTENT_HINT");
        Check((string?)recovered["details"]!["captureId"] == latest!.CaptureId
            && recovered["details"]!["sha256"]!.GetValue<string>() == Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))).ToLowerInvariant(),
            "released slot publishes the next independent capture with matching hash");
        Check((bool?)recovered["details"]!["sourceAuthority"] == false
            && !events.Any(e => (string?)e["event"] is "SOURCE" or "SCROLLED"),
            "hints never count as original SOURCE or authorize input");
        lease.Handle(Command("REQUEST_PAGE", 1));
        Check(lease.PendingRequestGateNs is not null, "independent SOURCE request remains available after collision");
        now = deadline; lease.Tick();
        Check(!lease.IsOpen && (string?)events.Last()["reason"] == "ABSOLUTE_SETTLEMENT_BUDGET_EXPIRED",
            "collision does not renew the original settlement deadline");
        Directory.CreateDirectory(root);
        File.WriteAllText(Path.Combine(root, "hint-slot-result.json"), new JsonObject {
            ["passed"] = true, ["offlineOnly"] = true, ["realCaptureOrInput"] = false,
            ["events"] = new JsonArray(events.Select(e => e.DeepClone()).ToArray()) }.ToJsonString(new() { WriteIndented = true }));
    }
}
