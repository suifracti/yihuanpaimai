using System.Text.Json.Nodes;
using WgcLiveHarness;

static class OrdinaryFrameExpiryChecks
{
    static void Check(bool ok, string reason) { if (!ok) throw new Exception(reason); }
    sealed class Source : IDisposable { public void Dispose() { } }
    public static void RunWait(string root, Func<long, long, CaptureDeliveryProof> fixture)
    {
        Directory.CreateDirectory(root);
        // Producer uses the same typed ordinary-only path as WGC selection.
        // Real frame pump, no WGC/real window/native input.
        foreach (var kind in new[] { "resume", "owner-fault", "user-stop" })
        {
            using var proceed = new ManualResetEventSlim(); var stopped = false;
            var p = fixture(2, 100_000_000_000);
            var fresh = new CapturedBgraFrame(4, 3, 16, new byte[48], p.ReadbackCompletedNs,
                "offline", p.SourceNs, 2, p, CaptureScopeEpoch: 7);
            using var pump = new LatestCapturePump<Source, CapturedBgraFrame>(() => new(), (_, stop) => {
                if (stop()) throw new OperationCanceledException();
                if (!proceed.Wait(10)) throw new OrdinaryFrameUnavailableException(new TimeoutException("DELIVERY_DEADLINE"));
                if (kind == "owner-fault") throw new InvalidOperationException("actual-owner-fault");
                return fresh;
            }, () => stopped, 10, _ => { });
            for (var retry = 0; retry < 3; retry++)
            {
                try { pump.Take(35); throw new Exception("missing ordinary wait"); }
                catch (TimeoutException) { Check(!pump.IsStopped && pump.FailureException is null,
                    "repeated missing ordinary frames do not terminate owner"); }
            }
            if (kind == "user-stop")
            {
                stopped = true;
                try { pump.Take(1000); throw new Exception("missing user stop"); }
                catch (OperationCanceledException) { }
            }
            else
            {
                proceed.Set();
                if (kind == "resume") Check(pump.Take(1000) == fresh && fresh.DeliveryProof!.Rejection(p.ReadbackCompletedNs + 1) is null,
                    "new qualified original, never an old substituted image");
                else
                {
                    try { pump.Take(1000); throw new Exception("missing owner fault"); }
                    catch (InvalidOperationException ex) { Check(ex.InnerException?.Message == "actual-owner-fault",
                        "real owner failure is not converted to waiting"); }
                }
            }
            Console.WriteLine("PASS: ordinary-wait-" + kind);
        }
        using (var pump = new LatestCapturePump<Source, object>(() => new(), (_, stop) => {
            while (!stop()) Thread.Sleep(5);
            throw new OperationCanceledException();
        }, () => false, 10, _ => { }))
        {
            try { pump.Invoke<object>((_, _) => throw new TimeoutException("DELIVERY_DEADLINE"), 1000);
                throw new Exception("explicit SOURCE timeout was retried"); }
            catch (TimeoutException ex) { Check(ex.Message == "DELIVERY_DEADLINE", "explicit SOURCE preserves original deadline failure"); }
        }
        Check(OrdinaryFrameUnavailableException.IsSelectionTimeout(new TimeoutException("DELIVERY_DEADLINE"))
            && !OrdinaryFrameUnavailableException.IsSelectionTimeout(new TimeoutException("DELIVERY_DEADLINE_AFTER_READBACK"))
            && !OrdinaryFrameUnavailableException.IsSelectionTimeout(new InvalidOperationException("DELIVERY_LOCAL_CLOCK_ORDER")),
            "only missing-frame selection timeout is ordinary waiting");
        Console.WriteLine("PASS: SOURCE timeout and other capture failures unchanged");
        var payload = new object();
        using (var pump = new LatestCapturePump<Source, object>(() => new(), (_, stop) => {
            if (stop()) throw new OperationCanceledException();
            return payload;
        }, () => false, 1, _ => { }))
        {
            var transfers = Task.Run(() => {
                for (var i = 0; i < 50; i++) Check(ReferenceEquals(pump.Take(1000), payload),
                    "concurrent explicit SOURCE cannot turn a selected ordinary frame into null");
            });
            for (var i = 0; i < 50; i++) pump.Invoke((_, _) => true, 1000, discardLatest: true);
            Check(transfers.Wait(3000), "ordinary transfers and explicit jobs both make progress");
        }
        Console.WriteLine("PASS: concurrent ordinary transfer and SOURCE discard");
        File.WriteAllText(Path.Combine(root, "result.json"), "{\"status\":\"PASS\",\"realInput\":false,\"newGame\":false}");
    }
    public static void Run(string root, Func<long, long, CaptureDeliveryProof> fixture)
    {
        Directory.CreateDirectory(root); var passed = new List<string>();
        void Pass(string name) { passed.Add(name); Console.WriteLine("PASS: " + name); }
        CapturedBgraFrame Frame(long seq, long gate = 100_000_000_000) {
            var p = fixture(seq, gate);
            return new(4, 3, 16, new byte[48], p.ReadbackCompletedNs, "offline", p.SourceNs, seq, p,
                CaptureScopeEpoch: 7);
        }
        var old = Frame(1); var observed = old.CaptureTimestampNs + 2_381_584_700;
        var recovery = new OrdinaryFrameRecovery();
        Check(OrdinaryFrameRecovery.Recoverable(old, observed), "real failed local age is discardable");
        recovery.Discard(old, observed);
        var fresh = Frame(2, observed + 100_000_000);
        var comparison = fresh.CaptureTimestampNs + 1;
        Check(recovery.ContextRejection(fresh) is null && fresh.DeliveryProof!.Rejection(comparison) is null,
            "new independent frame qualifies");
        Check(recovery.First!.CaptureId == old.DeliveryProof!.CaptureId, "first fault kept until successful admission");
        recovery.Accepted(); Check(recovery.First is null, "accepted new frame ends recovery");
        Pass("one expired ordinary frame discarded; independent fresh delivery admissible");

        recovery.Discard(old, observed);
        recovery.Discard(Frame(2, 100_500_000_000), observed + 1_000_000_000);
        var later = Frame(3, observed + 20_000_000_000);
        Check(recovery.First!.CaptureId == old.DeliveryProof!.CaptureId
            && recovery.ContextRejection(later) is null
            && later.DeliveryProof!.Rejection(later.CaptureTimestampNs + 1) is null,
            "loading longer than five seconds keeps first fault and admits a new qualified frame");
        Pass("expired ordinary frames remain discarded; long loading does not close observation");

        Check(!OrdinaryFrameRecovery.Recoverable(old, old.CaptureTimestampNs + 2_000_000_000), "two-second boundary unchanged");
        Check(!OrdinaryFrameRecovery.Recoverable(old, old.CaptureTimestampNs - 1), "future local readback cannot retry");
        var invalid = old with { DeliveryProof = old.DeliveryProof! with { DrainTakeCount = 0 } };
        Check(!OrdinaryFrameRecovery.Recoverable(invalid, observed), "invalid proof cannot retry");
        Check(!OrdinaryFrameRecovery.Recoverable(old with { CaptureTimestampNs = old.CaptureTimestampNs - 100 }, observed),
            "frame/proof timestamp mismatch cannot retry");
        foreach (var changed in new[] {
            fresh with { CaptureScopeEpoch = 8 },
            fresh with { DeliveryProof = fresh.DeliveryProof! with { ObservationSessionId = "other" } },
            fresh with { DeliveryProof = fresh.DeliveryProof! with { PoolEpoch = 2 } } })
            Check(recovery.ContextRejection(changed) == "ORDINARY_FRAME_RECOVERY_SCOPE_CHANGED", "old context cannot resume");
        Check(recovery.ContextRejection(fresh with { AcquisitionSequence = 1 }) == "DELIVERY_FRAME_BINDING_MISMATCH",
            "new frame payload must match proof");
        Check(recovery.ContextRejection(old) == "ORDINARY_FRAME_RECOVERY_INDEPENDENCE_UNPROVEN", "old capture never resumes");
        Pass("invalid/future/binding/context/independence failures are not recovered");

        // Real owner pump, inert source. No WGC, window or input calls.
        foreach (var kind in new[] { "fresh", "owner-failed", "no-frame" }) {
            using var proceed = new ManualResetEventSlim(); var calls = 0;
            using var pump = new LatestCapturePump<Source, CapturedBgraFrame>(() => new(), (_, stop) => {
                if (Interlocked.Increment(ref calls) == 1)
                    throw new OrdinaryFrameExpiredException(OrdinaryFrameDiscard.From(old, observed));
                while (!proceed.Wait(10)) if (stop()) throw new OperationCanceledException();
                if (kind == "owner-failed") throw new InvalidOperationException("known capture owner failure");
                return fresh;
            }, () => false, 20, reason => throw new Exception(reason));
            if (kind == "no-frame") {
                try { pump.Take(40); throw new Exception("missing timeout"); }
                catch (TimeoutException) { Check(pump.FailureException is null, "age-only discard is not permanent fault"); }
            } else {
                proceed.Set();
                if (kind == "fresh") Check(pump.Take(1000).DeliveryProof!.CaptureId == fresh.DeliveryProof!.CaptureId,
                    "ordinary owner resumes with exact fresh frame");
                else {
                    try { pump.Take(1000); throw new Exception("missing owner failure"); }
                    catch (InvalidOperationException ex) { Check(ex.InnerException?.Message == "known capture owner failure",
                        "real failure remains visible after recoverable discard"); }
                }
            }
            Pass("owner pump " + kind);
        }

        // Same production SOURCE lease; expired original must still be rejected.
        long now = 100_000_000_000; var events = new List<JsonObject>();
        using (var lease = new WarehouseEvidenceLease(Path.Combine(root, "source"), "offline", events.Add,
            () => now, capturePolicy: CapturePolicy.Delivery)) {
            var target = new JsonObject { ["targetHwnd"] = 123L };
            lease.UpdateContext(new("record", target, "map", 4, 3, true, true, now + 70_000_000_000, 1));
            JsonObject Cmd(string op, int n = 0) => new() {
                ["type"] = WarehouseEvidenceLease.ControlType, ["schemaVersion"] = WarehouseEvidenceLease.SchemaV2,
                ["operation"] = op, ["commandId"] = Guid.NewGuid().ToString("N"), ["nonce"] = "n" + n,
                ["observationSessionId"] = "offline", ["reviewSessionId"] = "review", ["reviewGeneration"] = 1,
                ["recordStableKey"] = "record", ["matchGeneration"] = 1L, ["expectedTargetInstance"] = target.DeepClone(),
                ["leaseToken"] = lease.LeaseToken, ["requestOrdinal"] = n, ["remainingPages"] = 16,
                ["remainingPngBytes"] = 64L * 1024 * 1024, ["pngEncoding"] = WarehouseEvidenceLease.PngEncoding };
            lease.Handle(Cmd("OPEN"));
            Check((int?)events.Last()["details"]?["remainingSourcePages"] == WarehouseEvidenceLease.MaxSources
                && (long?)events.Last()["details"]?["deadlineNs"] == now + 70_000_000_000, "original SOURCE limits");
            lease.Handle(Cmd("REQUEST_PAGE", 1)); var p = fixture(1, lease.PendingRequestGateNs!.Value);
            now = p.ReadbackCompletedNs + 2_381_584_700;
            Check(!lease.TryPublish(new(4, 3, 16, new byte[48], p.SourceNs, p.ReadbackCompletedNs, "offline", 1,
                "", 1, p, RequestGateNs: p.RequestNs, MatchGeneration: 1), () => true), "old SOURCE not admitted");
            Check(!lease.IsOpen && (string?)events.Last()["reason"] == "SOURCE_DELIVERY_PROOF_REJECTED"
                && (int?)events.Last()["details"]?["remainingSourcePages"] == WarehouseEvidenceLease.MaxSources
                && events.All(e => (string?)e["event"] != "SOURCE"), "ordinary recovery cannot promote SOURCE");
        }
        Pass("SOURCE proof qualification and explicit context deadline unchanged");
        File.WriteAllText(Path.Combine(root, "checks.json"), new JsonObject {
            ["offlineOnly"] = true, ["gameStarted"] = false, ["realInput"] = false,
            ["checks"] = new JsonArray(passed.Select(n => JsonValue.Create(n)).ToArray()) }.ToJsonString());
    }
}
