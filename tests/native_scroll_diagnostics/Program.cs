using System.Text.Json.Nodes;
using NteHost.Protocol;
using WgcLiveHarness;

// No real HWND or native send. Test the actual adapter/lease through injected OS outcomes.
var root = args.Single();
Directory.CreateDirectory(root);
var target = new JsonObject { ["targetHwnd"] = 123L, ["targetPid"] = 456,
    ["processInstanceToken"] = 789L, ["generation"] = 1L };
var context = new WarehouseSourceContext("record", target, "map", 1920, 1080, true, true, long.MaxValue, 1);
var all = new JsonArray();
void Check(bool ok, string name) { if (!ok) throw new Exception(name); Console.WriteLine("PASS: " + name); }

foreach (var name in new[] { "pid-mismatch", "client-resized", "guard-rejected", "coordinates-failed",
    "send-error", "send-zero-no-error", "send-success-no-displacement", "guard-lost-after-send", "send-exception" })
{
    var platform = new FakePlatform(); var logs = new List<JsonObject>(); var guards = 0;
    if (name == "pid-mismatch") platform.Target = platform.Target with { Pid = 999 };
    if (name == "client-resized") platform.Target = platform.Target with { Width = 1919 };
    if (name == "coordinates-failed") platform.Point = new(false, 0, 0, 5);
    if (name == "send-error") platform.Result = new(0, 0, 5);
    if (name == "send-zero-no-error") platform.Result = new(0, 0, 0);
    if (name == "send-exception") platform.Throws = true;
    bool Current() { guards++; return name != "guard-rejected" && (name != "guard-lost-after-send" || guards < 3); }
    bool result = false; bool threw = false;
    try { result = WarehouseWindowScroll.SendDown(context, Current, e => logs.Add((JsonObject)e.DeepClone()), platform); }
    catch (InvalidOperationException) { threw = true; }
    var noSend = name is "pid-mismatch" or "client-resized" or "guard-rejected" or "coordinates-failed";
    Check(platform.Sends == (noSend ? 0 : 1), name + " has exact bounded send behavior");
    if (noSend) Check(!result && logs.Last()["sendInterfaceInvoked"]!.GetValue<bool>() == false, name + " records NOT_SENT");
    else if (name == "send-exception") Check(threw && (string?)logs.Last()["classification"] == "SEND_OUTCOME_UNKNOWN", "exception preserves uncertainty, no retry");
    else {
        var api = logs.Single(e => (string?)e["stage"] == "send-interface-returned");
        Check(api["returnValue"]!.GetValue<long>() == platform.Result.ReturnValue
            && api["lastErrorRaw"]!.GetValue<int>() == platform.Result.Error
            && api["postScrollFrameReceived"]!.GetValue<bool>() == false, name + " preserves API evidence, not movement");
        if (name == "send-zero-no-error") Check((string?)api["errorMeaning"] == "GENERIC_FAILURE_NO_EXTENDED_ERROR", "zero error is not proof of success");
        if (name == "send-success-no-displacement") Check(result && (string?)api["classification"] == "SENT_DISPLACEMENT_UNPROVEN", "successful API does not prove movement");
        if (name == "guard-lost-after-send") Check(!result && (string?)logs.Last()["classification"] == "SENT_GUARD_LOST", "post-send guard loss cannot be reported NOT_SENT");
    }
    all.Add(new JsonObject { ["case"] = name, ["sendCalls"] = platform.Sends,
        ["logs"] = new JsonArray(logs.Select(e => e.DeepClone()).ToArray()) });
}
var loggingFailure = new FakePlatform();
Check(!WarehouseWindowScroll.SendDown(context, () => false, _ => throw new IOException(), loggingFailure)
    && loggingFailure.Sends == 0, "logging failure grants no input authority");

foreach (var scenario in new[] { "warehouse-changed", "latest-stale", "summary-missing", "qualified", "mapping-unproven" })
{
    long now = 100_000_000_000; var events = new List<JsonObject>(); var logs = new List<JsonObject>();
    DeliveryVisualSummary? latest = null; var adapterCalls = 0; var fake = new FakePlatform();
    using var lease = new WarehouseEvidenceLease(Path.Combine(root, scenario), "offline", events.Add, () => now,
        scrollDown: (c, current) => { adapterCalls++; return WarehouseWindowScroll.SendDown(c,
            () => current() && scenario != "mapping-unproven", logs.Add, fake); },
        capturePolicy: CapturePolicy.Delivery, latestSummary: () => latest, scrollDiagnosticLog: logs.Add);
    var c = context with { Width = 4, Height = 3, AbsoluteDeadlineNs = now + 70_000_000_000 };
    fake.Target = fake.Target with { Width = 4, Height = 3 };
    lease.UpdateContext(c);
    JsonObject Command(string op, int ordinal = 1) => new() {
        ["type"] = WarehouseEvidenceLease.ControlType, ["schemaVersion"] = WarehouseEvidenceLease.SchemaV2,
        ["operation"] = op, ["commandId"] = Guid.NewGuid().ToString("N"), ["nonce"] = "n" + ordinal,
        ["observationSessionId"] = "offline", ["reviewSessionId"] = "review", ["reviewGeneration"] = 1,
        ["recordStableKey"] = "record", ["expectedTargetInstance"] = target.DeepClone(), ["matchGeneration"] = 1L,
        ["leaseToken"] = lease.LeaseToken, ["remainingPages"] = 16, ["remainingPngBytes"] = 64L * 1024 * 1024,
        ["pngEncoding"] = WarehouseEvidenceLease.PngEncoding, ["requestOrdinal"] = ordinal, ["allowWindowScroll"] = true
    };
    lease.Handle(Command("OPEN")); Check(lease.IsOpen, scenario + " opens isolated lease");
    var saved = new List<JsonObject>(); var proofs = new List<CaptureDeliveryProof>();
    for (var seq = 1; seq <= 2; seq++) {
        lease.Handle(Command("REQUEST_PAGE", seq)); var request = lease.PendingRequestGateNs!.Value;
        var p = FixtureProof(seq, request); proofs.Add(p); now = p.ReadbackCompletedNs + 100;
        latest = new(p.CaptureId, 1, p.ReadbackCompletedNs, "scene", "warehouse", true);
        var pixels = Enumerable.Range(0, 48).Select(i => (byte)(i + seq)).ToArray();
        Check(lease.TryPublish(new(4, 3, 16, pixels, p.SourceNs, p.ReadbackCompletedNs,
            "2026-10-07T00:00:00Z", seq, "", seq, p, latest, request, 1), () => true), scenario + " saves source " + seq);
        var source = (JsonObject)events.Last()["source"]!; saved.Add((JsonObject)source.DeepClone());
        var ack = Command("ACK_SOURCE", seq);
        foreach (var key in new[] { "sourceLeaseId", "bmpSha256", "pixelSha256" }) ack[key] = source[key]!.DeepClone();
        ack["result"] = "SAVED"; lease.Handle(ack); now += 500_000_000;
    }
    if (scenario == "warehouse-changed") latest = latest! with { WarehouseRoiSha256 = "animated" };
    if (scenario == "latest-stale") now += 3_000_000_000;
    if (scenario == "summary-missing") latest = null;
    var scroll = Command("SCROLL_DOWN", 2);
    foreach (var key in new[] { "sourceLeaseId", "pixelSha256" }) scroll[key] = saved[1][key]!.DeepClone();
    scroll["savedCaptureId"] = proofs[0].CaptureId; scroll["stableCaptureId"] = proofs[1].CaptureId;
    lease.Handle(scroll);
    var qualification = logs.First(e => (string?)e["stage"] == "lease-qualification");
    if (scenario is "qualified" or "mapping-unproven") {
        Check(qualification["qualified"]!.GetValue<bool>() && adapterCalls == 1, scenario + " reaches adapter only after lease checks");
        Check(fake.Sends == (scenario == "qualified" ? 1 : 0), scenario + " target/mapping guard separates native send");
    } else {
        var expected = scenario == "warehouse-changed" ? "warehouseRoiMatches"
            : scenario == "latest-stale" ? "latestReadbackWithinDeadline" : "latestSummaryPresent";
        Check(adapterCalls == 0 && fake.Sends == 0
            && ((JsonArray)qualification["failedChecks"]!).Any(n => (string?)n == expected), scenario + " reports exact failed check without sending");
    }
    all.Add(new JsonObject { ["case"] = scenario, ["adapterCalls"] = adapterCalls, ["sendCalls"] = fake.Sends,
        ["logs"] = new JsonArray(logs.Select(e => e.DeepClone()).ToArray()) });
}
File.WriteAllText(Path.Combine(root, "behavior-results.json"), all.ToJsonString(new() { WriteIndented = true }));
Console.WriteLine("SCROLL_DIAGNOSTICS_PASS");

static CaptureDeliveryProof FixtureProof(long sequence, long request) {
    QpcClockSample Sample(long ns) {
        var ticks = checked(ns / 1_000_000_000 * ProtocolClock.Frequency
            + ns % 1_000_000_000 * ProtocolClock.Frequency / 1_000_000_000);
        return new(ticks, ProtocolClock.Frequency, ticks / ProtocolClock.Frequency,
            ticks % ProtocolClock.Frequency, ProtocolClock.TicksToNs(ticks));
    }
    var source = (request + 10_000_000) / 100;
    return new("offline", 1, sequence, request, request + 5_000_000_000, request + 100,
        request + 200, request + 300, Sample(request + 400), Sample(request + 100_000),
        source, source, 0, request + 100_100, request + 100_200)
        { DrainTakeCount = 1, BoundaryHeldCount = 0, ReleaseCompletedNs = request + 100 };
}

sealed class FakePlatform : WarehouseWindowScroll.IPlatform {
    public WarehouseWindowScroll.TargetState Target = new(456, 789, "HTGame.exe", "UnrealWindow", true, false, true, 1920, 1080);
    public WarehouseWindowScroll.ScreenPoint Point = new(true, 100, 100);
    public WarehouseWindowScroll.SendResult Result = new(1, 0, 0);
    public int Sends; public bool Throws;
    public WarehouseWindowScroll.TargetState ReadTarget(long hwnd) => Target;
    public WarehouseWindowScroll.ScreenPoint ToScreen(long hwnd, int x, int y) => Point;
    public WarehouseWindowScroll.SendResult Send(long hwnd, uint wheel, uint coordinates) {
        Sends++; if (Throws) throw new InvalidOperationException("injected-send-error"); return Result;
    }
}
