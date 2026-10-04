using System.Text.Json.Nodes;
using WgcLiveHarness;
using NteHost.Protocol;

var folder = args.Length > 0 ? args[0] : throw new Exception("isolated fixture root required");
Directory.CreateDirectory(folder);
if (args.Length > 2 && args[1] == "--protocol-fixture")
{
    // Fake compositor/context, actual original-file IO and actual stdin/stdout.
    // These cropped saved pixels are not evidence of live WGC capture or identity truth.
    var fixtures = args.Skip(2).ToArray();
    var first = File.ReadAllBytes(fixtures[0]);
    var fw = BitConverter.ToInt32(first, 18); var fh = -BitConverter.ToInt32(first, 22);
    var fakeTarget = new JsonObject { ["targetHwnd"] = 123L, ["targetPid"] = 456,
        ["generation"] = 1L, ["processInstanceToken"] = 789L };
    using var fixtureLease = new WarehouseEvidenceLease(folder, "test-native-session", e => {
        Console.WriteLine(e.ToJsonString()); Console.Out.Flush();
    });
    fixtureLease.UpdateContext(new WarehouseSourceContext("native_intake_development", fakeTarget,
        $"fixture:{fw}x{fh}", fw, fh, true, true, ProtocolClock.NowNs() + 70_000_000_000));
    long seq = 0;
    while (Console.ReadLine() is { } line)
    {
        if (JsonNode.Parse(line) is not JsonObject command) continue;
        if ((string?)command["type"] == "native_stop") break;
        fixtureLease.SignalClose(command); fixtureLease.Handle(command);
        if ((string?)command["operation"] != "REQUEST_PAGE") continue;
        var raw = File.ReadAllBytes(fixtures[(int)Math.Min(seq, fixtures.Length - 1)]);
        var pixels = raw.Skip(54).ToArray();
        var sourceTime = ProtocolClock.NowNs();
        fixtureLease.TryPublish(new WarehouseSourceFrame(fw, fh, fw * 4, pixels, sourceTime,
            ProtocolClock.NowNs(), "2026-09-30T10:00:00Z", ++seq,
            Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(pixels)).ToLowerInvariant(), seq), () => true);
    }
    return;
}
long now = 10_000_000_000;
var events = new List<JsonObject>();
var target = new JsonObject { ["targetHwnd"] = 123L, ["targetPid"] = 456,
    ["generation"] = 1L, ["processInstanceToken"] = 789L };
var lease = new WarehouseEvidenceLease(folder, "obs", e => events.Add(e), () => now);
var context = new WarehouseSourceContext("record", target, "map", 4, 3, true, true,
    now + 70_000_000_000);
lease.UpdateContext(context);
JsonObject Command(string op, int ordinal = 1) => new() {
    ["type"] = WarehouseEvidenceLease.ControlType, ["schemaVersion"] = WarehouseEvidenceLease.Schema,
    ["operation"] = op, ["commandId"] = Guid.NewGuid().ToString("N"),
    ["observationSessionId"] = "obs", ["reviewSessionId"] = "review", ["reviewGeneration"] = 1,
    ["recordStableKey"] = "record", ["expectedTargetInstance"] = target.DeepClone(),
    ["nonce"] = "nonce" + ordinal, ["requestOrdinal"] = ordinal,
    ["leaseToken"] = lease.LeaseToken, ["remainingPages"] = 16,
    ["remainingPngBytes"] = 64L * 1024 * 1024, ["pngEncoding"] = "opencv-bgr8-png-bound.v1"
};
void Check(bool pass, string name) { if (!pass) throw new Exception("FAIL: " + name); Console.WriteLine("PASS: " + name); }
WarehouseSourceFrame Frame(long sourceTime, long sequence = 1) {
    var pixels = Enumerable.Range(0, 48).Select(i => (byte)(i + sequence)).ToArray();
    return new(4, 3, 16, pixels, sourceTime, now, "2026-09-30T10:00:00Z", sequence,
        Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(pixels)).ToLowerInvariant(), sequence);
}
if (args.Length < 2 || args[1] != "--limits-only")
{
lease.Handle(Command("REQUEST_PAGE"));
Check(events.Last()["reason"]!.GetValue<string>() == "NO_ACTIVE_SOURCE_LEASE", "request without OPEN rejected");
var wrong = Command("OPEN"); wrong["observationSessionId"] = "old"; lease.Handle(wrong);
Check(events.Last()["event"]!.GetValue<string>() == "REJECTED", "old observation rejected");
lease.Handle(Command("OPEN")); Check(lease.IsOpen, "valid bounded OPEN");
lease.Handle(Command("REQUEST_PAGE"));
Check(!lease.TryPublish(Frame(now - 1), () => true), "queued old compositor frame rejected despite fresh readback");
Check(!lease.TryPublish(Frame(now), () => true), "equal request/source timestamp rejected");
now += 1_000_000;
Check(lease.TryPublish(Frame(now), () => true), "strictly post-request source admitted");
var published = events.Last(); var source = (JsonObject)published["source"]!;
Check(File.Exists(source["path"]!.GetValue<string>()) && lease.WrittenSources == 1, "SOURCE follows real original file write");
var ack = Command("ACK_SOURCE"); ack["sourceLeaseId"] = source["sourceLeaseId"]!.GetValue<string>();
ack["bmpSha256"] = source["bmpSha256"]!.GetValue<string>(); ack["pixelSha256"] = source["pixelSha256"]!.GetValue<string>(); ack["result"] = "SAVED";
lease.Handle(ack);
var low = Command("REQUEST_PAGE", 2); low["remainingPngBytes"] = 1L; lease.Handle(low);
Check(events.Last()["reason"]!.GetValue<string>() == "PNG_BUDGET_INSUFFICIENT" && lease.WrittenSources == 1,
    "PNG budget rejected before another original write");
lease.Handle(Command("REQUEST_PAGE", 3)); lease.SignalClose(Command("CLOSE"));
now += 1_000_000;
Check(!lease.TryPublish(Frame(now, 2), () => true) && lease.WrittenSources == 1, "reader cancellation fences pending publish");
lease.Handle(Command("CLOSE"));
lease.Handle(Command("OPEN")); lease.Handle(Command("REQUEST_PAGE", 4));
now += 1_000_000;
Check(!lease.TryPublish(Frame(now, 3), () => false), "lost target gate refuses source");
lease.Handle(Command("OPEN")); lease.Handle(Command("REQUEST_PAGE", 5));
now += 71_000_000_000;
Check(!lease.TryPublish(Frame(now, 4), () => true) && !lease.IsOpen, "absolute deadline cannot reset with OPEN");
lease.UpdateContext(context with { Width = 2560, Height = 1440 }); lease.Handle(Command("OPEN"));
Check(!lease.IsOpen, "1440p not negotiated around fixed-v1 geometry");
Console.WriteLine("HOST_LEASE_CONTRACTS_PASS");
}

// Newly wired IO/cumulative-limit boundaries; separate from the previously passed time matrix.
var capEvents = new List<JsonObject>();
using var cap = new WarehouseEvidenceLease(Path.Combine(folder, "cap"), "obs", capEvents.Add, () => now);
cap.UpdateContext(context with { AbsoluteDeadlineNs = now + 70_000_000_000 });
JsonObject CapCommand(string op, int ordinal = 1) { var cmd = Command(op, ordinal); cmd["leaseToken"] = cap.LeaseToken; return cmd; }
cap.Handle(CapCommand("OPEN"));
for (var i = 1; i <= 16; i++)
{
    cap.Handle(CapCommand("REQUEST_PAGE", i)); now += 1_000_000;
    if (!cap.TryPublish(Frame(now, i), () => true)) throw new Exception("bounded source refused: " + i);
    var s = capEvents.Last()["source"]!;
    if (i == 1)
    {
        now += 1_000_000;
        Check(!cap.TryPublish(Frame(now, 99), () => true) && cap.WrittenSources == 1,
            "one unacknowledged SOURCE cannot be replaced by the next observation frame");
    }
    var a = CapCommand("ACK_SOURCE", i);
    foreach (var key in new[] { "sourceLeaseId", "bmpSha256", "pixelSha256" }) a[key] = s[key]!.DeepClone();
    a["result"] = "SAVED"; cap.Handle(a);
}
cap.Handle(CapCommand("REQUEST_PAGE", 17));
Check(cap.WrittenSources == 16 && capEvents.Last()["reason"]!.GetValue<string>() == "SOURCE_LIMIT_REACHED", "17th source rejected before IO");
cap.Handle(CapCommand("CLOSE")); cap.Handle(CapCommand("OPEN"));
Check(!cap.IsOpen && cap.WrittenSources == 16, "OPEN does not reset frozen-match raw budget");
var blockedRoot = Path.Combine(folder, "blocked"); Directory.CreateDirectory(blockedRoot);
File.WriteAllText(Path.Combine(blockedRoot, "warehouse-sources"), "real filesystem failure fixture");
var blockedEvents = new List<JsonObject>();
using var blocked = new WarehouseEvidenceLease(blockedRoot, "obs", blockedEvents.Add, () => now);
blocked.UpdateContext(context with { AbsoluteDeadlineNs = now + 70_000_000_000 });
var bopen = Command("OPEN"); blocked.Handle(bopen);
var breq = Command("REQUEST_PAGE"); breq["leaseToken"] = blocked.LeaseToken; blocked.Handle(breq);
now += 1_000_000;
Check(!blocked.TryPublish(Frame(now, 1), () => true) && blocked.WrittenSources == 1
    && blockedEvents.Last()["reason"]!.GetValue<string>() == "SOURCE_WRITE_FAILED"
    && !blockedEvents.Any(e => e["event"]!.GetValue<string>() == "SOURCE"), "real source-write failure has no SOURCE and consumes bounded attempt");
var mapEvents = new List<JsonObject>();
using var mapped = new WarehouseEvidenceLease(Path.Combine(folder, "mapped"), "obs", mapEvents.Add, () => now);
mapped.UpdateContext(context with { AbsoluteDeadlineNs = now + 70_000_000_000 });
mapped.Handle(Command("OPEN"));
mapped.UpdateContext(context with { ClientMap = "changed", AbsoluteDeadlineNs = now + 70_000_000_000 });
Check(!mapped.IsOpen && mapped.WrittenSources == 0, "client mapping change closes source lease");
Console.WriteLine("HOST_IO_LIMIT_CONTRACTS_PASS");
using var eof = new WarehouseEvidenceLease(Path.Combine(folder, "eof"), "obs", _ => {}, () => now);
eof.UpdateContext(context with { AbsoluteDeadlineNs = now + 70_000_000_000 });
eof.SignalStop(); eof.Handle(Command("OPEN"));
Check(!eof.IsOpen && eof.WrittenSources == 0, "stdin EOF before queued OPEN cannot acquire a late source lease");
var bindEvents = new List<JsonObject>();
using var binding = new WarehouseEvidenceLease(Path.Combine(folder, "binding"), "obs", bindEvents.Add, () => now);
binding.UpdateContext(context with { AbsoluteDeadlineNs = now + 70_000_000_000 });
binding.Handle(Command("OPEN"));
var bindingRequest = Command("REQUEST_PAGE"); bindingRequest["leaseToken"] = binding.LeaseToken; binding.Handle(bindingRequest);
now += 1_000_000;
Check(!binding.TryPublish(Frame(now, 2) with { WorkerSequence = 1 }, () => true)
    && binding.WrittenSources == 0 && bindEvents.Last()["reason"]!.GetValue<string>() == "WORKER_SOURCE_HASH_MISMATCH",
    "worker receipt sequence must bind the exact source before IO");
