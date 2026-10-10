using System.Diagnostics;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Security.Cryptography;
using NteHost;
using WgcLiveHarness;

if (args.Contains("--mapping-only")) { MappingRecoveryChecks.Run(args[0]); return; }

if (args.Contains("--retained-boundary-only")) { RetainedBoundaryContracts.Run(); return; }
if (args.Contains("--advice-qualification-only")) { DeliveryContracts.AdviceQualificationOnly(); return; }
if (args.Contains("--advice-replay")) { DeliveryContracts.ReplayAdvice(args[0]); return; }
if (args.Contains("--visible-content-replay")) { DeliveryContracts.ReplayVisibleContent(args[0]); return; }
if (args.Contains("--delivery-only")) { DeliveryContracts.Run(args[0]); return; }

static void Require(bool value, string reason) { if (!value) throw new Exception(reason); }
if (args.Contains("--clock-startup-only"))
{
    // Actual failed-run values, independently preserved before this change.
    const long requestNs = 98329649541100, observedNs = 98329664116500, sourceTicks = 983296651024;
    var diagnostic = new RequestClockDiagnostics(requestNs, requestNs + 5_000_000_000L);
    var disposed = 0;
    var waits = 0;
    var futureFrame = new Packet(1, Array.Empty<byte>());
    Exception? rejected = null;
    try
    {
        RequestFrameSelector.Select(() => futureFrame, _ => diagnostic.Source(sourceTicks),
            _ => disposed++, _ => { waits++; return true; }, () => observedNs, () => false,
            requestNs, requestNs + 5_000_000_000L, out _);
    }
    catch (InvalidOperationException ex) { rejected = ex; }
    Require(rejected is not null && rejected.Message.Contains("aheadNs=985900"), "actual future counterexample accepted or altered");
    Require(disposed == 1 && waits == 0, "future frame was retained, waited through or retried");
    diagnostic.RecordComparison(sourceTicks, new QpcClockSample(983296641165, 10_000_000, 98329, 6641165, observedNs));
    diagnostic.Failure = rejected!.Message;
    var raw = JsonSerializer.Deserialize<JsonElement>(diagnostic.ToJson());
    Require(raw.GetProperty("readbackStatus").GetString() == "NOT_REACHED", "fake future frame counted as readback");
    var comparison = raw.GetProperty("comparisons")[0];
    Require(comparison.GetProperty("aheadNs").GetInt64() == 985900, "diagnostic replaced rejected comparison");
    var authority = comparison.GetProperty("nativeAuthorityAfterDecision");
    Require(authority.GetProperty("counterOk").GetBoolean() && authority.GetProperty("frequencyOk").GetBoolean(), "Win32 clock query failed");
    var ticks = authority.GetProperty("rawTicks").GetInt64();
    Require(ticks >= authority.GetProperty("before").GetProperty("rawTicks").GetInt64()
        && ticks <= authority.GetProperty("after").GetProperty("rawTicks").GetInt64(), "managed QPC and Win32 QPC not bracketed");
    Require(authority.GetProperty("frequencyHz").GetInt64() == Stopwatch.Frequency, "clock frequencies disagree");
    var wrapper = new InvalidOperationException("capture-owner-unavailable", rejected);
    Require(CaptureFailure.Reason(wrapper, "client-area-mapping-changed") == "source-clock-future-at-selection", "secondary failure hid original cause");
    Console.WriteLine(JsonSerializer.Serialize(new { passed = true, gameCapture = false, gameInput = false,
        futureFrameRejected = true, disposed, waits, managedNativeClockBracketPassed = true, diagnostic = raw }));
    return;
}
var results = new List<object>();
var ownerIds = new HashSet<int>();
int produced = 0;
var weakFrames = new List<WeakReference<Packet>>();
bool sourceDisposed = false;
using var stop = new CancellationTokenSource();
using var pump = new LatestCapturePump<Source, Packet>(() =>
{
    ownerIds.Add(Environment.CurrentManagedThreadId);
    return new Source(() => { ownerIds.Add(Environment.CurrentManagedThreadId); sourceDisposed = true; });
}, (source, cancelled) =>
{
    ownerIds.Add(Environment.CurrentManagedThreadId);
    for (int i = 0; i < 5; i++) { if (cancelled()) throw new OperationCanceledException(); Thread.Sleep(1); }
    var seq = Interlocked.Increment(ref produced);
    var packet = new Packet(seq, Enumerable.Repeat((byte)seq, 4096).ToArray());
    lock (weakFrames) weakFrames.Add(new(packet));
    return packet;
}, () => stop.IsCancellationRequested, 5, reason => throw new Exception(reason));
var business = pump.Take(1000);
var original = business.Pixels.ToArray();
// A genuinely blocked consumer: capture must advance while it owns its frame.
var slowWait = Stopwatch.StartNew();
Require(SpinWait.SpinUntil(() => Volatile.Read(ref produced) >= business.Sequence + 8, 2000),
    $"slow consumer blocked capture: acquired={produced}; initial={business.Sequence}");
var stats = JsonSerializer.SerializeToElement(pump.Statistics());
Require(stats.GetProperty("pendingFrames").GetInt32() == 1, "latest slot not bounded to one");
Require(stats.GetProperty("replacedFrames").GetInt64() >= 7, "replacement not charged");
Require(business.Pixels.SequenceEqual(original), "producer overwrote business-owned pixels");
var latest = pump.Take(1000);
Require(latest.Sequence > business.Sequence + 7, "FIFO backlog delivered instead of latest");
// Separate SOURCE job while the business buffer remains owned by its consumer.
var sourcePacket = pump.Invoke((source, cancelled) => new Packet(1000, Enumerable.Repeat((byte)77, 4096).ToArray()), 1000, discardLatest: true);
Thread.Sleep(80);
Require(sourcePacket.Pixels.All(b => b == 77) && business.Pixels.SequenceEqual(original), "SOURCE/business ownership corrupted");
Require(ownerIds.Count == 1 && !ownerIds.Contains(Environment.CurrentManagedThreadId), "source used outside owner thread");
GC.Collect(); GC.WaitForPendingFinalizers(); GC.Collect();
int liveFrames;
lock (weakFrames) liveFrames = weakFrames.Count(reference => reference.TryGetTarget(out _));
Require(liveFrames <= 4, "replaced frames retained an unbounded pixel queue");
results.Add(new { test = "slow-consumer-latest-source-ownership", passed = true, acquired = produced, liveNormalFrames = liveFrames, statistics = pump.Statistics() });

// Actual SOURCE writer while normal capture keeps replacing frames. Its hash
// must still bind to the private explicit packet, not the current latest slot.
long now = 10_000_000_000;
var events = new List<JsonObject>();
var target = new JsonObject { ["targetHwnd"] = 12, ["targetPid"] = 34, ["generation"] = 1, ["processInstanceToken"] = 56 };
var wheelCalls = 0;
using (var lease = new WarehouseEvidenceLease(Path.Combine(args[0], "build/native-observation-reliability-20261005/source-concurrency"), "offline", events.Add, () => now,
    scrollDown: (_, _) => { wheelCalls++; return true; }))
{
    lease.UpdateContext(new WarehouseSourceContext("match", target, "map", 32, 32, true, true, now + 70_000_000_000));
    JsonObject Command(string operation) => new() {
        ["type"] = WarehouseEvidenceLease.ControlType, ["schemaVersion"] = WarehouseEvidenceLease.Schema,
        ["operation"] = operation, ["commandId"] = Guid.NewGuid().ToString("N"), ["nonce"] = "nonce",
        ["observationSessionId"] = "offline", ["reviewSessionId"] = "review", ["reviewGeneration"] = 1,
        ["recordStableKey"] = "match", ["expectedTargetInstance"] = target.DeepClone(),
        ["leaseToken"] = lease.LeaseToken, ["requestOrdinal"] = 1, ["remainingPages"] = 16,
        ["allowWindowScroll"] = true,
        ["remainingPngBytes"] = 64L * 1024 * 1024, ["pngEncoding"] = WarehouseEvidenceLease.PngEncoding };
    lease.Handle(Command("OPEN")); lease.Handle(Command("REQUEST_PAGE"));
    now += 100_000_000;
    var sha = Convert.ToHexString(SHA256.HashData(sourcePacket.Pixels)).ToLowerInvariant();
    var beforeSave = produced;
    Require(lease.TryPublish(new WarehouseSourceFrame(32, 32, 128, sourcePacket.Pixels, now-1, now,
        "offline", 1, sha, 1), () => {
        Require(SpinWait.SpinUntil(() => Volatile.Read(ref produced) > beforeSave, 1000), "capture stopped during SOURCE save");
        return true;
    }), "SOURCE did not save its bound private pixels");
    var path = (string)events.Single(e => (string?)e["event"] == "SOURCE")["source"]!["path"]!;
    Require(File.ReadAllBytes(path).Skip(54).SequenceEqual(sourcePacket.Pixels), "SOURCE disk pixels overwritten by ordinary capture");
    var saved = (JsonObject)events.Single(e => (string?)e["event"] == "SOURCE")["source"]!;
    var ack = Command("ACK_SOURCE");
    ack["result"] = "SAVED";
    foreach (var key in new[] { "sourceLeaseId", "pixelSha256", "bmpSha256" }) ack[key] = saved[key]!.DeepClone();
    lease.Handle(ack);
    now += 3_000_000_000;
    var wheel = Command("SCROLL_DOWN");
    wheel["sourceLeaseId"] = saved["sourceLeaseId"]!.DeepClone();
    wheel["pixelSha256"] = saved["pixelSha256"]!.DeepClone();
    lease.Handle(wheel);
    Require(wheelCalls == 0 && !lease.IsOpen, "expired page still sent a wheel");
    lease.SignalStop();
    Require(!lease.TryPublish(new WarehouseSourceFrame(32, 32, 128, sourcePacket.Pixels, now, now, "offline", 2, sha, 2), () => true), "SOURCE published after stop");
    results.Add(new { test = "actual-source-save-during-capture", passed = true, path, pixelSha256 = sha, expiredPageWheelCalls = wheelCalls });
}
var cancellationEntered = new ManualResetEventSlim();
var blocked = Task.Run(() =>
{
    try
    {
        pump.Invoke<int>((source, cancelled) => { cancellationEntered.Set(); while (!cancelled()) Thread.Sleep(2); throw new OperationCanceledException(); }, 30000);
        return false;
    }
    catch (OperationCanceledException) { return true; }
});
Require(cancellationEntered.Wait(1000), "explicit job did not start");
var watch = Stopwatch.StartNew(); stop.Cancel(); pump.Dispose();
Require(blocked.Wait(1000) && blocked.Result && sourceDisposed, "cancel did not release owner/job");
Require(watch.ElapsedMilliseconds < 1000, "cancel waited for OCR/frame deadline");
results.Add(new { test = "cancel-blocked-source", passed = true, elapsedMs = watch.ElapsedMilliseconds });

using (var failed = new LatestCapturePump<Source, Packet>(() => new Source(() => {}),
    (_, _) => { Thread.Sleep(60); throw new InvalidOperationException("injected-window-loss"); }, () => false, 5, reason => throw new Exception(reason)))
{
    Thread.Sleep(100);
    try { failed.Take(100); throw new Exception("failed owner returned an old frame"); }
    catch (InvalidOperationException ex) { Require(ex.InnerException?.Message == "injected-window-loss", "failure reason lost"); }
    try { failed.Invoke((_, _) => false, 100); throw new Exception("dead capture owner impersonated a negative mapping probe"); }
    catch (InvalidOperationException ex) { Require(ex.InnerException?.Message == "injected-window-loss", "mapping probe masked capture failure"); }
    results.Add(new { test = "capture-failure-no-restart", passed = true, statistics = failed.Statistics() });
}

// A driver-like uninterruptible read cannot be called a confirmed exit.
using (var entered = new ManualResetEventSlim())
using (var release = new ManualResetEventSlim())
{
    string? refusal = null;
    bool disposed = false;
    using var stuck = new LatestCapturePump<Source, Packet>(() => new Source(() => disposed = true),
        (_, _) => { entered.Set(); release.Wait(5000); return new Packet(1, new byte[4]); },
        () => false, 5, reason => refusal = reason);
    Require(entered.Wait(1000), "uninterruptible fixture did not enter");
    watch.Restart(); stuck.Dispose();
    Require(refusal == "capture-owner-exit-unconfirmed-after-1500ms" && !disposed,
        "blocked owner falsely reported disposal or lost refusal");
    var unconfirmed = stuck.Statistics();
    Require(!JsonSerializer.SerializeToElement(unconfirmed).GetProperty("ownerExited").GetBoolean(), "blocked thread falsely reported exit");
    release.Set(); stuck.Dispose();
    Require(disposed, "eventually returning owner failed to release its own source");
    results.Add(new { test = "uninterruptible-owner-reports-unconfirmed", passed = true, elapsedMs = watch.ElapsedMilliseconds, unconfirmed });
}

// Real Windows MMF producer, fake pixels only. No WGC/window/process/input.
using (var ring = new MmfFrameRingWriter())
{
    ring.Create("offline-mmfscope", Guid.NewGuid().ToString("N"));
    var pixels = new byte[4 * 16 * 16];
    var held = ring.Publish("offline-mmfscope", pixels, 16, 16, 64, 1)!;
    for (int i = 0; i < 3; i++) Require(ring.Publish("offline-mmfscope", pixels, 16, 16, 64, 2+i) is not null, "ring unexpectedly full");
    Require(ring.Publish("offline-mmfscope", pixels, 16, 16, 64, 5) is null, "locked MMF overwritten");
    Require(!ring.TryRelease("another-session", held.BufferIndex, held.Header.Sequence, out _), "wrong session released MMF");
    Require(!ring.TryRelease("offline-mmfscope", held.BufferIndex, held.Header.Sequence+1, out _), "wrong sequence released MMF");
    Require(ring.TryRelease("offline-mmfscope", held.BufferIndex, held.Header.Sequence, out _), "exact ACK did not release");
    Require(ring.Publish("offline-mmfscope", pixels, 16, 16, 64, 6) is not null, "exact release could not be reused");
    results.Add(new { test = "real-mmf-exact-ack", passed = true });
}

var repo = Path.GetFullPath(args[0]);
using (var supervisor = new SupervisorSession(new SupervisorSession.Options {
    SessionId = "offline-cancel", ContractsDir = Path.Combine(repo, "architecture/v2/contracts"), WorkDir = Path.Combine(repo, "build/native-observation-reliability-20261005") }))
{
    using var cancel = new CancellationTokenSource();
    var waiter = Task.Run(() => { try { supervisor.WaitForMessage(_ => true, 30000, out _, () => cancel.IsCancellationRequested); return false; } catch (OperationCanceledException) { return true; } });
    Thread.Sleep(60); watch.Restart(); cancel.Cancel();
    Require(waiter.Wait(500) && waiter.Result, "Supervisor wait did not cancel");
    results.Add(new { test = "supervisor-blocked-wait-cancel", passed = true, elapsedMs = watch.ElapsedMilliseconds });
}
Console.WriteLine(JsonSerializer.Serialize(new { passed = true, gameCapture = false, gameInput = false, results }, new JsonSerializerOptions { WriteIndented = true }));

sealed class Source(Action dispose) : IDisposable { public void Dispose() => dispose(); }
sealed record Packet(int Sequence, byte[] Pixels);
