using System.Text.Json.Nodes;
using WgcLiveHarness;

static class OrdinaryFrameExpiryChecks
{
    static void Check(bool ok, string reason) { if (!ok) throw new Exception(reason); }
    sealed class Source : IDisposable { public void Dispose() { } }
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
        var recovery = new OrdinaryFrameRecovery(5000);
        Check(OrdinaryFrameRecovery.Recoverable(old, observed), "real failed local age is discardable");
        recovery.Discard(old, observed); var originalDeadline = recovery.DeadlineNs;
        var fresh = Frame(2, observed + 100_000_000);
        var comparison = fresh.CaptureTimestampNs + 1;
        Check(recovery.ContextRejection(fresh) is null && fresh.DeliveryProof!.Rejection(comparison) is null
            && !recovery.Expired(comparison), "new independent frame qualifies");
        Check(recovery.First!.CaptureId == old.DeliveryProof!.CaptureId, "first fault kept until successful admission");
        recovery.Accepted(); Check(recovery.First is null, "accepted new frame ends recovery");
        Pass("one expired ordinary frame discarded; independent fresh delivery admissible");

        recovery.Discard(old, observed);
        recovery.Discard(Frame(2, 100_500_000_000), observed + 1_000_000_000);
        Check(recovery.DeadlineNs == originalDeadline && !recovery.Expired(originalDeadline - 1)
            && recovery.Expired(originalDeadline) && recovery.First!.CaptureId == old.DeliveryProof!.CaptureId,
            "persistent expired deliveries do not renew five-second deadline or first fault");
        Check(recovery.RemainingWaitMs(originalDeadline - 2_000_000, 5000) == 2, "Take uses remaining wait only");
        Pass("continuous unusable frames terminate at original bounded deadline");

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
            Check((int?)events.Last()["details"]?["remainingSourcePages"] == 16
                && (long?)events.Last()["details"]?["deadlineNs"] == now + 70_000_000_000, "original SOURCE limits");
            lease.Handle(Cmd("REQUEST_PAGE", 1)); var p = fixture(1, lease.PendingRequestGateNs!.Value);
            now = p.ReadbackCompletedNs + 2_381_584_700;
            Check(!lease.TryPublish(new(4, 3, 16, new byte[48], p.SourceNs, p.ReadbackCompletedNs, "offline", 1,
                "", 1, p, RequestGateNs: p.RequestNs, MatchGeneration: 1), () => true), "old SOURCE not admitted");
            Check(!lease.IsOpen && (string?)events.Last()["reason"] == "SOURCE_DELIVERY_PROOF_REJECTED"
                && (int?)events.Last()["details"]?["remainingSourcePages"] == 16
                && events.All(e => (string?)e["event"] != "SOURCE"), "ordinary recovery cannot promote SOURCE");
        }
        Pass("SOURCE proof qualification, sixteen originals and seventy-second deadline unchanged");
        File.WriteAllText(Path.Combine(root, "checks.json"), new JsonObject {
            ["offlineOnly"] = true, ["gameStarted"] = false, ["realInput"] = false,
            ["checks"] = new JsonArray(passed.Select(n => JsonValue.Create(n)).ToArray()) }.ToJsonString());
    }
}
