using System.Text.Json.Nodes;
using WgcLiveHarness;

// No WGC/real window/native API. A failed content guard cannot authorize input;
// proven pre-send rejection needs fresh support; proven successful sending may
// wait for post-scroll SOURCE, but never permits repeating that input.
static class ContentRecheckChecks
{
    static void Check(bool value, string reason) { if (!value) throw new Exception(reason); }
    public static void RunAdapter(string root, Func<long, long, CaptureDeliveryProof> fixture, bool secondScroll = false)
    {
        var cases = secondScroll ? new[] { "before-target", "before-send", "identity", "mapping",
            "content-and-scene", "send-unknown", "send-exception", "post-send", "user-stop",
            "post-scene", "post-identity", "post-mapping", "post-expired", "post-context", "post-stop", "post-unqualified" }
            : new[] { "before-target", "before-send", "identity", "geometry", "mapping",
            "content-and-scene", "unmarked", "context-replaced", "expired", "send-error",
            "send-unknown", "send-exception", "post-send" };
        foreach (var kind in cases)
        {
            var failingAttempt = secondScroll ? 2 : 1;
            long now = 100_000_000_000;
            long deadlineForPost = now + 70_000_000_000;
            var events = new List<JsonObject>(); var logs = new List<JsonObject>();
            DeliveryVisualSummary? latest = null; var attempts = 0;
            var platform = new FakePlatform(); platform.Target = platform.Target with { Width = 4, Height = 3 };
            var target = new JsonObject { ["targetHwnd"] = 123L, ["targetPid"] = 456, ["processInstanceToken"] = 789L };
            var context = new WarehouseSourceContext("record", target, "map", 4, 3, true, true, now + 70_000_000_000, 1);
            WarehouseEvidenceLease? active = null;
            var work = Path.Combine(root, kind);
            using var lease = new WarehouseEvidenceLease(work, "offline", events.Add, () => now,
                scrollDown: (c, current) => {
                    attempts++;
                    if (attempts == failingAttempt)
                    {
                        if (kind is "before-target" or "content-and-scene" or "unmarked" or "context-replaced" or "expired")
                            latest = latest! with { ScrollContentRoiSha256 = "changed" };
                        if (kind == "content-and-scene") latest = latest! with { SceneRoiSha256 = "other" };
                        if (kind == "before-send") platform.BeforeCoordinates = () => latest = latest! with { ScrollContentRoiSha256 = "changed" };
                        if (kind == "identity") platform.Target = platform.Target with { Pid = 999 };
                        if (kind == "geometry") platform.Target = platform.Target with { Width = 5 };
                        if (kind == "send-error") platform.Result = new(0, 0, 5);
                        if (kind == "send-unknown") platform.Result = new(0, 0, 0);
                        if (kind == "send-exception") platform.Throws = true;
                        if (kind == "post-send" || kind.StartsWith("post-")) platform.AfterSend = () => {
                            latest = latest! with { CaptureId = "offline/1/6", ReadbackNs = now + 5_000_000,
                                ScrollContentRoiSha256 = "changed" };
                            now += 10_000_000; // independent readback during the successful send
                            if (kind == "post-scene") latest = latest with { SceneRoiSha256 = "other" };
                            if (kind == "post-identity") platform.Target = platform.Target with { Pid = 999 };
                            if (kind == "post-expired") now = deadlineForPost;
                            if (kind == "post-context") active!.UpdateContext(context with { MatchGeneration = 2 });
                            if (kind == "post-stop") active!.SignalStop();
                            if (kind == "post-unqualified") latest = latest with { ActionQualified = false };
                        };
                        if (kind == "user-stop") active!.SignalStop();
                        if (kind == "unmarked") { Check(!current(), "unmarked content refusal fixture"); return false; }
                    }
                    var result = WarehouseWindowScroll.SendDown(c,
                        () => current() && !(attempts == failingAttempt && (kind == "mapping"
                            || kind == "post-mapping" && platform.Sends >= failingAttempt))
                            && (kind != "post-identity" || platform.Target.Pid == 456), logs.Add, platform);
                    if (kind == "context-replaced") active!.UpdateContext(context with { });
                    if (kind == "expired") now = context.AbsoluteDeadlineNs;
                    return result;
                }, capturePolicy: CapturePolicy.Delivery, latestSummary: () => latest, scrollDiagnosticLog: logs.Add);
            active = lease; lease.UpdateContext(context);
            JsonObject Cmd(string op, int ordinal = 0) => new() {
                ["type"] = WarehouseEvidenceLease.ControlType, ["schemaVersion"] = WarehouseEvidenceLease.SchemaV2,
                ["operation"] = op, ["commandId"] = Guid.NewGuid().ToString("N"), ["nonce"] = "n" + ordinal,
                ["observationSessionId"] = "offline", ["reviewSessionId"] = "review", ["reviewGeneration"] = 1,
                ["recordStableKey"] = "record", ["matchGeneration"] = 1L, ["expectedTargetInstance"] = target.DeepClone(),
                ["leaseToken"] = lease.LeaseToken, ["requestOrdinal"] = ordinal, ["remainingPages"] = 16,
                ["remainingPngBytes"] = 64L * 1024 * 1024, ["pngEncoding"] = WarehouseEvidenceLease.PngEncoding,
                ["allowWindowScroll"] = true, ["retainIndependentOriginals"] = true };
            lease.Handle(Cmd("OPEN"));
            var deadline = events.Last()["details"]!["deadlineNs"]!.GetValue<long>();
            var proofs = new List<CaptureDeliveryProof>(); var sources = new List<JsonObject>();
            void Save(int seq, string content)
            {
                lease.Handle(Cmd("REQUEST_PAGE", seq)); var gate = lease.PendingRequestGateNs!.Value;
                var proof = fixture(seq, gate); proofs.Add(proof); now = proof.ReadbackCompletedNs + 1;
                latest = new(proof.CaptureId, 1, proof.ReadbackCompletedNs, "scene", "warehouse", true, ScrollContentRoiSha256: content);
                Check(lease.TryPublish(new(4, 3, 16, Enumerable.Repeat((byte)seq, 48).ToArray(),
                    proof.SourceNs, proof.ReadbackCompletedNs, "offline", seq, "", seq, proof, latest, gate, 1), () => true),
                    kind + ": independent SOURCE saved");
                var source = (JsonObject)events.Last()["source"]!; sources.Add((JsonObject)source.DeepClone());
                var ack = Cmd("ACK_SOURCE", seq);
                foreach (var key in new[] { "sourceLeaseId", "pixelSha256", "bmpSha256" }) ack[key] = source[key]!.DeepClone();
                ack["result"] = "SAVED"; lease.Handle(ack); now += 500_000_000;
            }
            JsonObject Scroll(int seq)
            {
                var command = Cmd("SCROLL_DOWN", seq);
                foreach (var key in new[] { "sourceLeaseId", "pixelSha256" }) command[key] = sources[seq - 1][key]!.DeepClone();
                command["savedCaptureId"] = proofs[seq - 2].CaptureId;
                command["stableCaptureId"] = proofs[seq - 1].CaptureId; command["wheelDelta"] = -1080;
                return command;
            }
            Save(1, "old"); Save(2, "old");
            if (secondScroll)
            {
                Save(3, "old"); lease.Handle(Scroll(3));
                Check(lease.IsOpen && platform.Sends == 1 && (string?)events.Last()["event"] == "SCROLLED",
                    "first pulse succeeds before second-pulse fault");
                Save(4, "moved"); Save(5, "moved");
            }
            var ordinal = secondScroll ? 5 : 2;
            var token = lease.LeaseToken; var old = Scroll(ordinal); lease.Handle(old);
            File.WriteAllText(Path.Combine(work, "first-receipt.json"), events.Last().ToJsonString());
            var recovery = events.SingleOrDefault(e => (string?)e["details"]?["classification"] == "NOT_SENT_CONTENT_SUPPORT_RECHECK");
            var safe = kind is "before-target" or "before-send";
            Check((recovery is not null) == safe, kind + ": only known pre-send content refusal permits recovery");
            Check(platform.Sends == (secondScroll ? 1 : 0) + (kind.StartsWith("send-") || kind.StartsWith("post-") ? 1 : 0), kind + ": exact API attempts");
            if (kind == "post-send")
            {
                Check(lease.IsOpen && lease.LeaseToken == token && (string?)events.Last()["event"] == "SCROLLED",
                    "successful send with only old-content mismatch waits for independent post-scroll SOURCE");
                File.WriteAllText(Path.Combine(work, "sent-receipt.json"), events.Last().ToJsonString());
                var sends = platform.Sends; lease.Handle(old);
                Check(platform.Sends == sends && attempts == failingAttempt, "sent pulse cannot replay");
                platform.AfterSend = null;
                Save(ordinal + 1, "changed");
                Check((int?)events.Last()["details"]?["remainingSourcePages"] == 16 - ordinal - 1,
                    "new independent SOURCE keeps original budget");
                now = deadline; lease.Tick(); Check(!lease.IsOpen, "post-send wait keeps original deadline");
            }
            else if (safe)
            {
                Check(lease.IsOpen && lease.LeaseToken == token && (string?)recovery!["event"] == "REJECTED"
                    && (bool?)recovery["details"]?["sendInterfaceInvoked"] == false
                    && (string?)recovery["details"]?["adapterStage"] == (kind == "before-target"
                        ? "CURRENT_GUARD_REJECTED_BEFORE_TARGET_READ" : "CURRENT_GUARD_REJECTED_BEFORE_SEND"), "explicit same-lease NOT_SENT");
                File.WriteAllText(Path.Combine(work, "rejected-receipt.json"), recovery!.ToJsonString());
                lease.Handle(old);
                Check(attempts == failingAttempt && (string?)events.Last()["reason"] == "SCROLL_SOURCE_NOT_SAVED_OR_REUSED", "old pulse cannot replay");
                platform.BeforeCoordinates = null;
                Save(ordinal + 1, "changed"); Save(ordinal + 2, "changed"); lease.Handle(Scroll(ordinal + 2));
                Check(attempts == failingAttempt + 1 && platform.Sends == (secondScroll ? 2 : 1)
                    && (string?)events.Last()["event"] == "SCROLLED", "fresh independent support admits new pulse");
                Check((int?)events.Last()["details"]?["remainingSourcePages"] == 16 - ordinal - 2, "SOURCE budget is not reset");
                now = deadline; lease.Tick(); Check(!lease.IsOpen, "original deadline is not renewed");
            }
            else
            {
                // Handle reports adapter exceptions as REJECTED; Python must terminate
                // on that unsafe receipt. The old pulse is consumed even on an exception.
                Check(kind == "send-exception" ? (string?)events.Last()["reason"] == "injected-send-error" : !lease.IsOpen,
                    kind + ": terminal/unsafe rejection retained");
                var sends = platform.Sends; lease.Handle(old);
                Check(attempts == failingAttempt && platform.Sends == sends, kind + ": no replay after failed/uncertain send");
                if (kind == "send-exception") Check(logs.Any(e => (string?)e["classification"] == "SEND_OUTCOME_UNKNOWN"
                    && (bool?)e["sendInterfaceInvoked"] == true), "exception preserves actual API invocation");
                if (kind.StartsWith("post-"))
                {
                    Check(logs.Any(e => (string?)e["classification"] == "SENT_GUARD_LOST"
                        && (bool?)e["sendInterfaceInvoked"] == true), "post-send rejection is never NOT_SENT");
                    Check(events.Count(e => (string?)e["event"] == "SCROLLED") == (secondScroll ? 1 : 0),
                        "failed second pulse has no success receipt");
                }
            }
            File.WriteAllText(Path.Combine(work, "adapter-check.json"), new JsonObject {
                ["case"] = kind, ["status"] = "PASS", ["sendCalls"] = platform.Sends,
                ["events"] = new JsonArray(events.Select(e => e.DeepClone()).ToArray()),
                ["diagnostics"] = new JsonArray(logs.Select(e => e.DeepClone()).ToArray()) }.ToJsonString());
            Console.WriteLine("PASS: " + (secondScroll ? "second-scroll-" : "adapter-") + kind);
        }
    }
    public static void Run(string root, Func<long, long, CaptureDeliveryProof> fixture, bool diagnosticOnly = false)
    {
        foreach (var kind in diagnosticOnly ? new[] { "diagnostic-snapshot", "diagnostic-write-blocked" }
            : new[] { "content-only", "content-and-scene", "adapter-unknown" })
        {
            long now = 100_000_000_000; var events = new List<JsonObject>(); var calls = 0;
            DeliveryVisualSummary? latest = null;
            var diagnosticReads = 0;
            var work = Path.Combine(root, kind);
            using var lease = new WarehouseEvidenceLease(work, "offline", events.Add, () => now,
                scrollDown: (_, guard) => { calls++; return kind != "adapter-unknown" && guard(); },
                capturePolicy: CapturePolicy.Delivery, latestSummary: () => {
                    var frozen = latest;
                    // Simulate a concurrent new publication after the guard read.
                    if (diagnosticOnly && frozen?.DiagnosticFrame is not null && ++diagnosticReads >= 2)
                        latest = frozen with { CaptureId = "offline/1/replacement", DiagnosticFrame = null };
                    return frozen;
                });
            var target = new JsonObject { ["targetHwnd"] = 123L };
            lease.UpdateContext(new("record", target, "map", 4, 3, true, true, now + 70_000_000_000, 1));
            JsonObject Cmd(string op, int ordinal = 0) => new() {
                ["type"] = WarehouseEvidenceLease.ControlType, ["schemaVersion"] = WarehouseEvidenceLease.SchemaV2,
                ["operation"] = op, ["commandId"] = Guid.NewGuid().ToString("N"), ["nonce"] = "n" + ordinal,
                ["observationSessionId"] = "offline", ["reviewSessionId"] = "review", ["reviewGeneration"] = 1,
                ["recordStableKey"] = "record", ["matchGeneration"] = 1L, ["expectedTargetInstance"] = target.DeepClone(),
                ["leaseToken"] = lease.LeaseToken, ["requestOrdinal"] = ordinal, ["remainingPages"] = 16,
                ["remainingPngBytes"] = 64L * 1024 * 1024, ["pngEncoding"] = WarehouseEvidenceLease.PngEncoding,
                ["allowWindowScroll"] = true, ["retainIndependentOriginals"] = true };
            lease.Handle(Cmd("OPEN"));
            var deadline = events.Last()["details"]!["deadlineNs"]!.GetValue<long>();
            var proofs = new List<CaptureDeliveryProof>(); var sources = new List<JsonObject>();
            void Save(int seq, string content)
            {
                lease.Handle(Cmd("REQUEST_PAGE", seq)); var gate = lease.PendingRequestGateNs!.Value;
                var proof = fixture(seq, gate); proofs.Add(proof); now = proof.ReadbackCompletedNs + 1;
                latest = new(proof.CaptureId, 1, proof.ReadbackCompletedNs, "scene", "warehouse", true,
                    ScrollContentRoiSha256: content);
                Check(lease.TryPublish(new(4, 3, 16, Enumerable.Repeat((byte)seq, 48).ToArray(),
                    proof.SourceNs, proof.ReadbackCompletedNs, "offline", seq, "", seq, proof, latest, gate, 1),
                    () => true), "new independent SOURCE must save");
                var source = (JsonObject)events.Last()["source"]!; sources.Add((JsonObject)source.DeepClone());
                var ack = Cmd("ACK_SOURCE", seq);
                foreach (var key in new[] { "sourceLeaseId", "pixelSha256", "bmpSha256" }) ack[key] = source[key]!.DeepClone();
                ack["result"] = "SAVED"; lease.Handle(ack); now += 500_000_000;
            }
            JsonObject Scroll(int seq)
            {
                var command = Cmd("SCROLL_DOWN", seq);
                foreach (var key in new[] { "sourceLeaseId", "pixelSha256" }) command[key] = sources[seq - 1][key]!.DeepClone();
                command["savedCaptureId"] = proofs[seq - 2].CaptureId;
                command["stableCaptureId"] = proofs[seq - 1].CaptureId;
                command["wheelDelta"] = -1080;
                return command;
            }
            Save(1, "old"); Save(2, "old");
            if (kind != "adapter-unknown") latest = latest! with { ScrollContentRoiSha256 = "new" };
            if (kind == "content-and-scene") latest = latest! with { SceneRoiSha256 = "other-scene" };
            long diagnosticSourceNs = 0;
            if (diagnosticOnly)
            {
                var proof = fixture(3, now); now = proof.ReadbackCompletedNs + 1;
                diagnosticSourceNs = proof.SourceNs;
                latest = latest! with { CaptureId = proof.CaptureId, ReadbackNs = proof.ReadbackCompletedNs,
                    DiagnosticFrame = new(4, 3, 16, Enumerable.Repeat((byte)7, 48).ToArray(),
                        proof.ReadbackCompletedNs, "2026-10-10T00:00:00Z", proof.SourceNs, 3, proof) };
                if (kind == "diagnostic-write-blocked")
                    File.WriteAllText(Path.Combine(work, "warehouse-scroll-refusal"), "blocked directory fixture");
            }
            var oldScroll = Scroll(2); lease.Handle(oldScroll);
            if (diagnosticOnly)
            {
                Check(lease.IsOpen && calls == 0 && events.Count(e => (string?)e["event"] == "SOURCE") == 2,
                    "diagnostic never sends or grants SOURCE; IO failure does not close lease");
                Check((int?)events.Last()["details"]?["remainingSourcePages"] == 14, "diagnostic leaves SOURCE budget");
                if (kind == "diagnostic-snapshot")
                {
                    var dir = Path.Combine(work, "warehouse-scroll-refusal");
                    var bmp = File.ReadAllBytes(Path.Combine(dir, "first-refusal.bmp"));
                    Check(bmp.Length == 102 && bmp.Skip(54).All(value => value == 7), "exact refused full frame retained");
                    var meta = JsonNode.Parse(File.ReadAllText(Path.Combine(dir, "first-refusal.json")))!;
                    Check((string?)meta["captureId"] == "offline/1/3" && (long?)meta["readbackTimestampNs"] == now - 1
                        && (long?)meta["sourceTimestampNs"] == diagnosticSourceNs,
                        "metadata follows refused snapshot, not replacement");
                    Check((bool?)meta["sourceAuthority"] == false && (bool?)meta["formalFactsQualified"] == false
                        && (string?)meta["failedChecks"]?[0] == "scrollContentQuantizationSupported",
                        "diagnostic qualification and failure explicit");
                    Check((string?)meta["pixelSha256"] == Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(
                        Enumerable.Repeat((byte)7, 48).ToArray())).ToLowerInvariant(), "raw payload hash bound");
                    latest = latest! with { CaptureId = "offline/1/4" };
                    Save(3, "old"); Save(4, "old");
                    latest = latest! with { ScrollContentRoiSha256 = "another-change" };
                    lease.Handle(Scroll(4));
                    Check(File.ReadAllBytes(Path.Combine(dir, "first-refusal.bmp")).SequenceEqual(bmp)
                        && Directory.GetFiles(dir).Length == 2, "only earliest refusal preserved");
                }
                now = deadline; lease.Tick(); Check(!lease.IsOpen, "diagnostic does not renew deadline");
                Console.WriteLine("PASS: " + kind);
                continue;
            }
            if (kind == "content-only")
            {
                var rejected = events.Last();
                Check(lease.IsOpen && calls == 0 && (string?)rejected["event"] == "REJECTED"
                    && (string?)rejected["reason"] == "SCROLL_CONTENT_CHANGED_BEFORE_SEND"
                    && (bool?)rejected["details"]?["sendInterfaceInvoked"] == false, "not sent content-only recheck");
                lease.Handle(oldScroll);
                Check(calls == 0 && (string?)events.Last()["reason"] == "SCROLL_SOURCE_NOT_SAVED_OR_REUSED",
                    "consumed source cannot resend");
                Save(3, "new"); Save(4, "new"); lease.Handle(Scroll(4));
                Check(calls == 1 && (string?)events.Last()["event"] == "SCROLLED", "new support admits next scroll");
                Check((int?)events.Last()["details"]?["remainingSourcePages"] == 12, "SOURCE budget not reset");
                now = deadline; lease.Tick();
                Check(!lease.IsOpen, "original deadline still expires");
            }
            else Check(!lease.IsOpen && (string?)events.Last()["event"] == "CLOSED"
                && calls == (kind == "adapter-unknown" ? 1 : 0), "other guards or unknown adapter must stop");
            Console.WriteLine("PASS: " + kind);
        }
    }
}
