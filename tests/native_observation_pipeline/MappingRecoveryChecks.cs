using System.Text.Json.Nodes;
using WgcLiveHarness;

internal static class MappingRecoveryChecks
{
    private static void Check(bool value, string reason) { if (!value) throw new Exception(reason); }
    public static void Run(string root)
    {
        var expected = new MappingGeometry(1922, 1112, 1920, 1080, 1, 31);
        // Independently preserved startup geometry; screen translation alone is legal.
        var observed = new MappingMeasurement(1922, 1112, 1920, 1080, 101, 231, 100, 200, 1922, 1112);
        var current = MappingProbe.Compare(expected, observed, "WindowRect");
        Check(current.State == MappingState.Current, "same mapping rejected");
        Check(MappingProbe.Compare(expected, observed with { ClientOriginY = 232 }, "WindowRect").State == MappingState.Changed, "measured offset change missed");
        Check(MappingProbe.Compare(expected, observed with { ClientWidth = 1280 }, "WindowRect").State == MappingState.Changed, "measured size change missed");
        Check(MappingProbe.Compare(expected, observed with { BoundsWidth = null }, "WindowRect").State == MappingState.Unavailable, "missing measurement treated as change");
        var unavailable = current with { State = MappingState.Unavailable, Stage = "GetClientRect", Error = "win32:5", Observed = new(1922, 1112) };
        long now = 0;
        int publications = 0, inputs = 0, reads = 0;
        var recovery = new MappingRecovery();
        var oldEpoch = recovery.Epoch;
        var events = new List<JsonObject>();
        var target = new JsonObject { ["targetHwnd"] = 123L, ["targetPid"] = 456,
            ["generation"] = 1L, ["processInstanceToken"] = 789L };
        using var lease = new WarehouseEvidenceLease(root, "obs", events.Add, () => 10_000_000_000 + now * 1_000_000,
            scrollDown: (_, _) => { inputs++; return true; });
        var context = new WarehouseSourceContext("record", target, "map", 4, 3, true, true, 80_000_000_000, CaptureScopeEpoch: oldEpoch);
        lease.UpdateContext(context);
        JsonObject Command(string op, string? token = null) => new() {
            ["type"] = WarehouseEvidenceLease.ControlType, ["schemaVersion"] = WarehouseEvidenceLease.Schema,
            ["operation"] = op, ["commandId"] = Guid.NewGuid().ToString("N"), ["observationSessionId"] = "obs",
            ["reviewSessionId"] = "review", ["reviewGeneration"] = 1, ["recordStableKey"] = "record",
            ["expectedTargetInstance"] = target.DeepClone(), ["nonce"] = "one", ["requestOrdinal"] = 1,
            ["leaseToken"] = token ?? lease.LeaseToken, ["remainingPages"] = 16,
            ["remainingPngBytes"] = 64L * 1024 * 1024, ["pngEncoding"] = WarehouseEvidenceLease.PngEncoding };
        lease.Handle(Command("OPEN")); Check(lease.IsOpen, "fixture lease did not open");
        var oldToken = lease.LeaseToken;
        var originalDeadline = (long)events.Last()["details"]!["deadlineNs"]!;
        lease.Handle(Command("REQUEST_PAGE")); Check(lease.PendingRequestGateNs is not null, "first request was not admitted");
        recovery.Ensure(() => ++reads < 3 ? unavailable : current, () => false, () => true,
            () => lease.SignalMappingPause(recovery.Epoch),
            (stage, _, _) => { if (stage == "recovered") lease.SignalMappingRecovered(); }, () => now,
            ms => {
                now += ms;
                Check(!recovery.Publish(oldEpoch, () => publications++), "published during missing mapping");
                lease.Handle(Command("SCROLL_DOWN", oldToken));
                Check(!lease.IsOpen && inputs == 0, "input/lease alive during pause");
                Check((string?)events.Last()["reason"] == "SOURCE_MAPPING_REVALIDATION_REQUIRED", "wheel refused for an unrelated reason");
            });
        Check(reads == 3 && recovery.FirstProbe == unavailable, "first measurement was lost");
        Check(!recovery.Publish(oldEpoch, () => publications++), "old frame survived recovery");
        Check(!lease.IsOpen, "old lease revived on recovery");
        lease.Handle(Command("OPEN")); Check(!lease.IsOpen, "mapping recovery without fresh context opened lease");
        lease.UpdateContext(context); lease.Handle(Command("OPEN")); Check(!lease.IsOpen, "old context revived lease");
        lease.UpdateContext(context with { CaptureScopeEpoch = recovery.Epoch });
        lease.Handle(Command("OPEN")); Check(lease.IsOpen && lease.LeaseToken != oldToken, "fresh context did not establish a new lease");
        Check((long)events.Last()["details"]!["deadlineNs"]! == originalDeadline, "recovery extended settlement deadline");
        lease.Handle(Command("REQUEST_PAGE", oldToken)); Check(lease.PendingRequestGateNs is null, "old lease token admitted");
        Check(recovery.Publish(recovery.Epoch, () => publications++), "fresh frame rejected after identity/mapping revalidation");
        Check(publications == 1 && inputs == 0, "unexpected publication/input");
        for (int i = 0; i < 31; i++)
        {
            lease.Handle(Command("REQUEST_PAGE")); Check(lease.PendingRequestGateNs is not null, "remaining request budget was reduced");
            lease.Close("fixture-close"); lease.Handle(Command("OPEN"));
        }
        Check(!lease.IsOpen && (string?)events.Last()["reason"] == "SOURCE_LIMIT_REACHED", "pause/reopen reset the 32-request budget");

        foreach (var terminal in new[] { MappingState.Changed, MappingState.TargetInvalid, MappingState.Stopped, MappingState.Unavailable })
        {
            var gate = new MappingRecovery(); long ticks = 0; int probes = 0; bool stop = false, identity = true;
            MappingRejectedException? rejected = null;
            try {
                gate.Ensure(() => { probes++; return unavailable; }, () => stop, () => identity,
                    () => { }, (_, _, _) => { }, () => ticks,
                    ms => { ticks += ms; if (terminal == MappingState.Stopped) stop = true;
                        if (terminal == MappingState.TargetInvalid) identity = false; },
                    initial: terminal == MappingState.Changed ? current with { State = terminal, Stage = "compare", Observed = observed with { ClientOriginY = 232 } } : unavailable);
            } catch (MappingRejectedException ex) { rejected = ex; }
            Check(rejected is not null && !gate.Publish(gate.Epoch, () => publications++), "terminal branch granted publication");
            Check(rejected!.FirstProbe.Stage == (terminal == MappingState.Changed ? "compare" : "GetClientRect"), "earliest reason overwritten");
            if (terminal == MappingState.Unavailable) Check(ticks <= 2000 && probes <= 40 && rejected.Message == "client-area-mapping-probe-deadline", "unbounded probe wait");
            else Check(rejected.LastProbe.State == terminal, "stop/target/change misclassified");
            Check(CaptureFailure.Reason(new Exception("capture-owner-stopped", rejected), "fallback") == rejected.Message, "downstream masked root reason");
        }
        Console.WriteLine("PASS mapping: partial/current/changed measurements, bounded recovery, zero paused publication/input, stale frames/leases/context rejected, fixed deadline, target/stop/root-cause preservation");
    }
}
