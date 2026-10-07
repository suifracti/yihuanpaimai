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
if (args.Length > 1 && args[1] == "--settlement-wiring-only")
{
    // Settlement eligibility is independent of frozen-bill publication; no WGC or input API.
    lease.UpdateContext(context with { SettlementCaptureEligible = false });
    lease.Handle(Command("OPEN"));
    Check(!lease.IsOpen, "non-settlement cannot open SOURCE");
    lease.UpdateContext(context with { SettlementCaptureEligible = true });
    lease.Handle(Command("OPEN"));
    Check(lease.IsOpen, "observed settlement can open without bill freeze authority");
    lease.Handle(Command("REQUEST_PAGE"));
    lease.UpdateContext(context with { SettlementCaptureEligible = false });
    Check(!lease.IsOpen && lease.PendingRequestGateNs is null, "leaving settlement cancels pending source");
    lease.UpdateContext(context with { SettlementCaptureEligible = true });
    lease.Handle(Command("OPEN")); lease.Handle(Command("REQUEST_PAGE"));
    lease.SignalStop();
    Check(!lease.IsOpen && lease.PendingRequestGateNs is null, "stop revokes early settlement request immediately");
    using var next = new WarehouseEvidenceLease(Path.Combine(folder, "next"), "obs", events.Add, () => now);
    next.UpdateContext(context);
    next.Handle(Command("OPEN"));
    next.UpdateContext(context with { RecordKey = "next-match", AbsoluteDeadlineNs = now + 70_000_000_000 });
    Check(!next.IsOpen, "next match retires old lease");
    var nextOpen = Command("OPEN"); nextOpen["recordStableKey"] = "next-match";
    next.Handle(nextOpen);
    Check(next.IsOpen && next.WrittenSources == 0, "new match has separate unchanged budget");
    var stale = Command("REQUEST_PAGE");
    next.Handle(stale);
    Check(next.PendingRequestGateNs is null, "old match command cannot request next-match source");
    next.UpdateContext(context with { RecordKey = "next-match", ClientMap = "invalid-mapping", AbsoluteDeadlineNs = now + 70_000_000_000 });
    Check(!next.IsOpen, "mapping change revokes source");
    Console.WriteLine("SETTLEMENT_WIRING_CONTRACTS_PASS");
    return;
}
WarehouseSourceFrame Frame(long sourceTime, long sequence = 1) {
    var pixels = Enumerable.Range(0, 48).Select(i => (byte)(i + sequence)).ToArray();
    return new(4, 3, 16, pixels, sourceTime, now, "2026-09-30T10:00:00Z", sequence,
        Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(pixels)).ToLowerInvariant(), sequence);
}
if (args.Length > 1 && args[1] == "--trigger-watch-only")
{
    var triggerRoot = Path.Combine(folder, "trigger-watch");
    var probeNow = 20_000_000_000L;
    var deadline = probeNow + 70_000_000_000L;
    var triggerEvents = new List<JsonObject>();
    using var trigger = new WarehouseEvidenceLease(triggerRoot, "obs", e => triggerEvents.Add(e), () => probeNow);
    var triggerContext = context with { AbsoluteDeadlineNs = deadline };
    trigger.UpdateContext(triggerContext);
    var watchId = Guid.NewGuid().ToString("N");
    WarehouseSourceFrame TriggerFrame(long timestamp, long sequence)
    {
        var pixels = Enumerable.Range(0, 48).Select(i => (byte)(i + sequence)).ToArray();
        return new WarehouseSourceFrame(4, 3, 16, pixels, timestamp - 1_000_000, timestamp,
            "2026-10-06T00:00:00Z", sequence,
            Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(pixels)).ToLowerInvariant(), sequence);
    }
    JsonObject TriggerCommand(string operation, string? probeId = null) => new() {
        ["type"] = WarehouseEvidenceLease.ControlType, ["schemaVersion"] = WarehouseEvidenceLease.Schema,
        ["operation"] = operation, ["commandId"] = Guid.NewGuid().ToString("N"),
        ["nonce"] = Guid.NewGuid().ToString("N"), ["observationSessionId"] = "obs",
        ["watchId"] = watchId, ["recordStableKey"] = "record",
        ["expectedTargetInstance"] = target.DeepClone(), ["matchGeneration"] = 0,
        ["clientMap"] = "map", ["maxProbes"] = WarehouseEvidenceLease.MaxTriggerProbes,
        ["minimumIntervalNs"] = WarehouseEvidenceLease.MinTriggerProbeIntervalNs,
        ["probeId"] = probeId, ["result"] = "REJECTED", ["reason"] = "offline-fixture",
        ["reasonCodes"] = new JsonArray(JsonValue.Create("WAREHOUSE_NOT_TOP"))
    };
    // Fixture context has generation 0, matching the default WarehouseSourceContext.
    trigger.Handle(TriggerCommand("WATCH_TRIGGER"));
    Check(triggerEvents.Last()["event"]!.GetValue<string>() == "TRIGGER_WATCH_ARMED",
        "bounded trigger watch arms with fixed source scope");
    Check(trigger.PublishTriggerProbe(TriggerFrame(probeNow, 1), () => true), "first bounded probe publishes");
    var firstProbe = triggerEvents.Last();
    var firstDetails = (JsonObject)firstProbe["details"]!;
    var firstPath = Path.Combine(triggerRoot, firstDetails["relativePath"]!.GetValue<string>().Replace('/', Path.DirectorySeparatorChar));
    var firstBytes = File.ReadAllBytes(firstPath);
    var replacementBlocked = false;
    try { File.WriteAllBytes(firstPath, new byte[] { 1, 2, 3 }); }
    catch (IOException) { replacementBlocked = true; }
    catch (UnauthorizedAccessException) { replacementBlocked = true; }
    Check(replacementBlocked && File.ReadAllBytes(firstPath).SequenceEqual(firstBytes),
        "pending probe file cannot be replaced while its Host owner holds it");
    probeNow += WarehouseEvidenceLease.MinTriggerProbeIntervalNs;
    var publishedProbeCount = triggerEvents.Count(e => (string?)e["event"] == "TRIGGER_PROBE");
    Check(!trigger.PublishTriggerProbe(TriggerFrame(probeNow, 2), () => true)
        && triggerEvents.Count(e => (string?)e["event"] == "TRIGGER_PROBE") == publishedProbeCount
        && File.ReadAllBytes(firstPath).SequenceEqual(firstBytes),
        "slow consumer keeps one pending probe and does not queue or overwrite the next frame");
    var firstAck = TriggerCommand("ACK_TRIGGER_PROBE", firstDetails["probeId"]!.GetValue<string>());
    trigger.Handle(firstAck);
    Check(triggerEvents.Any(e => (string?)e["event"] == "TRIGGER_PROBE_ACKED") && !File.Exists(firstPath),
        "exact probe ACK releases only the consumed original");
    var staleAck = TriggerCommand("ACK_TRIGGER_PROBE", firstDetails["probeId"]!.GetValue<string>());
    trigger.Handle(staleAck);
    Check(triggerEvents.Last()["reason"]!.GetValue<string>() == "STALE_TRIGGER_PROBE_ACK",
        "late duplicate ACK cannot release a later probe");
    for (var ordinal = 2; ordinal <= WarehouseEvidenceLease.MaxTriggerProbes; ordinal++)
    {
        probeNow += WarehouseEvidenceLease.MinTriggerProbeIntervalNs;
        Check(trigger.PublishTriggerProbe(TriggerFrame(probeNow, ordinal), () => true),
            "bounded probe attempt " + ordinal);
        var published = triggerEvents.Last();
        var details = (JsonObject)published["details"]!;
        Check((int)details["probeOrdinal"]! == ordinal
            && (int)details["sourcePagesWritten"]! == 0
            && (int)details["sourceRequestAttempts"]! == 0,
            "probe budget and SOURCE counters are separately recorded " + ordinal);
        trigger.Handle(TriggerCommand("ACK_TRIGGER_PROBE", details["probeId"]!.GetValue<string>()));
    }
    Check(triggerEvents.Last()["reason"]!.GetValue<string>() == "TRIGGER_PROBE_LIMIT_REACHED",
        "32nd probe ends watch with an explicit finite-budget reason");
    probeNow += WarehouseEvidenceLease.MinTriggerProbeIntervalNs;
    Check(!trigger.PublishTriggerProbe(TriggerFrame(probeNow, 33), () => true)
        && triggerEvents.Count(e => (string?)e["event"] == "TRIGGER_PROBE") == WarehouseEvidenceLease.MaxTriggerProbes,
        "probe 33 is rejected before file publication");

    // The interval is independently enforced after ACK; it does not depend on
    // the pending-slot guard or the application loop's sleep cadence.
    long intervalNow = 30_000_000_000L;
    var intervalEvents = new List<JsonObject>();
    using (var interval = new WarehouseEvidenceLease(Path.Combine(folder, "interval-probe"), "obs",
        e => intervalEvents.Add(e), () => intervalNow))
    {
        interval.UpdateContext(context with { AbsoluteDeadlineNs = intervalNow + 70_000_000_000L });
        var priorWatchId = watchId;
        watchId = Guid.NewGuid().ToString("N");
        interval.Handle(TriggerCommand("WATCH_TRIGGER"));
        Check(interval.PublishTriggerProbe(TriggerFrame(intervalNow, 1), () => true),
            "interval fixture publishes initial probe");
        var initial = (JsonObject)intervalEvents.Last()["details"]!;
        interval.Handle(TriggerCommand("ACK_TRIGGER_PROBE", initial["probeId"]!.GetValue<string>()));
        intervalNow += WarehouseEvidenceLease.MinTriggerProbeIntervalNs - 1;
        var eventCountBeforeEarlyAttempt = intervalEvents.Count(e => (string?)e["event"] == "TRIGGER_PROBE");
        Check(!interval.PublishTriggerProbe(TriggerFrame(intervalNow, 2), () => true)
            && intervalEvents.Count(e => (string?)e["event"] == "TRIGGER_PROBE") == eventCountBeforeEarlyAttempt,
            "probe inside the minimum interval is rejected without consuming an attempt");
        intervalNow++;
        Check(interval.PublishTriggerProbe(TriggerFrame(intervalNow, 2), () => true),
            "probe is eligible exactly at the minimum interval");
        var second = (JsonObject)intervalEvents.Last()["details"]!;
        Check((int)second["probeOrdinal"]! == 2, "interval rejection does not consume the bounded probe budget");
        interval.Handle(TriggerCommand("ACK_TRIGGER_PROBE", second["probeId"]!.GetValue<string>()));
        watchId = priorWatchId;
    }

    var stopEvents = new List<JsonObject>();
    var stopLease = new WarehouseEvidenceLease(Path.Combine(folder, "stop-probe"), "obs", e => stopEvents.Add(e), () => probeNow);
    var stopDeadline = probeNow + 70_000_000_000L;
    stopLease.UpdateContext(context with { AbsoluteDeadlineNs = stopDeadline });
    var stopId = Guid.NewGuid().ToString("N");
    var stopOpen = TriggerCommand("WATCH_TRIGGER"); stopOpen["watchId"] = stopId;
    stopOpen["recordStableKey"] = "record"; stopOpen["expectedTargetInstance"] = target.DeepClone();
    stopOpen["matchGeneration"] = 0;
    stopLease.Handle(stopOpen);
    Check(stopLease.PublishTriggerProbe(TriggerFrame(probeNow, 1), () => true), "stop fixture has one pending probe");
    var stopDetails = (JsonObject)stopEvents.Last()["details"]!;
    var stopPath = Path.Combine(folder, "stop-probe", stopDetails["relativePath"]!.GetValue<string>().Replace('/', Path.DirectorySeparatorChar));
    stopLease.SignalStop();
    Check(!stopLease.PublishTriggerProbe(TriggerFrame(probeNow + 1, 2), () => true),
        "stop fences an in-flight probe publisher");
    stopLease.Dispose();
    Check(!File.Exists(stopPath), "Host stop closes owner and removes pending temporary evidence");

    var scopeEvents = new List<JsonObject>();
    using var changed = new WarehouseEvidenceLease(Path.Combine(folder, "next-match-probe"), "obs", e => scopeEvents.Add(e), () => probeNow);
    changed.UpdateContext(context with { AbsoluteDeadlineNs = stopDeadline });
    var scopeOpen = TriggerCommand("WATCH_TRIGGER"); scopeOpen["watchId"] = Guid.NewGuid().ToString("N");
    scopeOpen["recordStableKey"] = "record"; scopeOpen["expectedTargetInstance"] = target.DeepClone();
    scopeOpen["matchGeneration"] = 0;
    changed.Handle(scopeOpen);
    Check(changed.PublishTriggerProbe(TriggerFrame(probeNow, 1), () => true), "scope-change fixture publishes once");
    var scopeDetails = (JsonObject)scopeEvents.Last()["details"]!;
    var scopePath = Path.Combine(folder, "next-match-probe", scopeDetails["relativePath"]!.GetValue<string>().Replace('/', Path.DirectorySeparatorChar));
    changed.UpdateContext(context with { RecordKey = "next-match", AbsoluteDeadlineNs = stopDeadline + 1 });
    Check(!File.Exists(scopePath) && scopeEvents.Any(e => (string?)e["reason"] == "TRIGGER_SCOPE_CHANGED"),
        "next match boundary immediately revokes and deletes the previous pending probe");
    Console.WriteLine("TRIGGER_WATCH_CONTRACTS_PASS");
    return;
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
