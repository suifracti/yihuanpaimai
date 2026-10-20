using System.Text.Json;
using NteHost.DomainActions;
using WgcLiveHarness;

// Real saved clock/proof fields, fixture request binding and blank pixels.
// No window, WGC owner, input backend or Main history is constructed.
static class InputCaptureChecks
{
    static void Require(bool ok, string why) { if (!ok) throw new Exception(why); }
    public static void Run()
    {
        using var file = JsonDocument.Parse(File.ReadAllText("tests/fixtures/native-input-delivery-timing.json"));
        var options = new JsonSerializerOptions { PropertyNameCaseInsensitive = true };
        var proofs = file.RootElement.GetProperty("frames").EnumerateArray()
            .Select(x => x.Deserialize<CaptureDeliveryProof>(options)!).ToArray();
        long request = proofs[0].RequestNs, deadline = request + 2_000_000_000, now = request;
        // Replay both original deliveries within one operation's unchanged deadline.
        proofs[0] = proofs[0] with { DeadlineNs = deadline };
        proofs[1] = proofs[1] with { RequestNs = request, DeadlineNs = deadline };
        CapturedBgraFrame Frame(CaptureDeliveryProof p) => new(4, 4, 16, new byte[64],
            p.ReadbackCompletedNs, "", p.SourceNs, p.AcquisitionSequence, p, CaptureScopeEpoch: p.PoolEpoch);
        var frames = proofs.Select(Frame).ToArray();
        Require(proofs.All(p => p.Qualified && p.SourceMarkerProgress && p.OriginStatus == "CONSISTENT_AT_READ")
            && frames[0].SourceTimestampNs <= request && frames[1].SourceTimestampNs > request,
            "REAL_TIMING_FIXTURE_INVALID");
        var window = new WindowBinding(1, 2, 3, 0);
        var scope = new ActionScope("fixture-match", 1, 1, 100, 100, "AUCTION_READY", "fixture-lease", deadline,
            window, 0, 1, now, true, true, true, true, false, false)
            { MatchGeneration = 1, ObservationSessionId = "input-capture-fixture" };
        NativeDomainFrame? Adapt(CapturedBgraFrame frame) => WgcDomainCaptureAdapter.FromIndependentCapture(
            frame, scope, new(4, 4, 0, 0), request, now, window, proofs[0].PoolEpoch);
        int calls = 0;
        var selected = WgcDomainCaptureAdapter.CaptureForInput((wait, req, end) => {
            Require(req == request && end == deadline && wait is > 0 and <= 2000, "UNCHANGED_CAPTURE_BOUNDARY");
            // Production DeadlineForRequest computes request + timeout, NOT now + timeout.
            Require(Math.Min(end, req + wait * 1_000_000L) == deadline, "PRODUCTION_INNER_DEADLINE_MUST_MATCH");
            var frame = frames[Math.Min(calls++, 1)]; now = frame.CaptureTimestampNs + 1_000_000; return frame;
        }, request, deadline, () => now);
        Console.WriteLine($"saved timing replay calls={calls}, postRequest={selected.SourceTimestampNs > request}, qualified={Adapt(selected) is not null}");
        Require(calls == 2 && Adapt(selected) is not null, "WAIT_FOR_POST_REQUEST_SOURCE");
        var badProofs = new[] {
            proofs[0] with { ReleaseCompletedNs = 0 },
            proofs[0] with { PreviousMarkerNs = proofs[0].SourceNs },
            proofs[0] with { SourceTicks = proofs[0].ReadbackCompletedNs / 100 + 1,
                RepeatedSourceTicks = proofs[0].ReadbackCompletedNs / 100 + 1,
                ReadbackSourceTicks = proofs[0].ReadbackCompletedNs / 100 + 1 }
        };
        foreach (var p in badProofs)
        {
            now = request; calls = 0;
            var bad = WgcDomainCaptureAdapter.CaptureForInput((_, _, _) => {
                calls++; now = p.ReadbackCompletedNs + 1_000_000; return Frame(p);
            }, request, deadline, () => now);
            Require(calls == 1 && Adapt(bad) is null, "INVALID_FUTURE_STALLED_MUST_NOT_RETRY");
        }
        now = request; calls = 0;
        var expired = WgcDomainCaptureAdapter.CaptureForInput((_, _, _) => {
            calls++; now = frames[0].CaptureTimestampNs + 500_000_001; return frames[0];
        }, request, deadline, () => now);
        Require(calls == 1 && Adapt(expired) is null, "EXPIRED_MUST_NOT_RETRY");
        now = request; calls = 0;
        var exhausted = WgcDomainCaptureAdapter.CaptureForInput((_, _, _) => {
            calls++; now = frames[0].CaptureTimestampNs + calls * 1_000_000; return frames[0];
        }, request, deadline, () => now);
        Require(calls == 4 && Adapt(exhausted) is null, "BOUNDED_WAIT_MUST_REMAIN_UNQUALIFIED");
        now = request; calls = 0;
        var ended = WgcDomainCaptureAdapter.CaptureForInput((_, _, _) => {
            calls++; now = deadline; return frames[0];
        }, request, deadline, () => now);
        Require(calls == 1 && Adapt(ended) is null, "ORIGINAL_DEADLINE_MUST_END_WAIT");
        now = request; calls = 0;
        bool scopeChanged = false;
        try
        {
            WgcDomainCaptureAdapter.CaptureForInput((_, _, _) => {
                var frame = frames[Math.Min(calls++, 1)]; now = frame.CaptureTimestampNs + 1_000_000;
                return calls == 2 ? frame with { CaptureScopeEpoch = frame.CaptureScopeEpoch + 1 } : frame;
            }, request, deadline, () => now);
        }
        catch (InvalidOperationException e) when (e.Message == "input-capture-scope-changed") { scopeChanged = true; }
        Require(scopeChanged && calls == 2, "SCOPE_CHANGE_MUST_STOP_WAIT");
        Console.WriteLine("PASS saved timing replay waits for a qualified post-request source; zero input");
        Console.WriteLine("PASS invalid/future/stalled/expired/deadline/exhaustion/scope-change remain rejected; zero input");
    }

    public static void RunFuture()
    {
        using var file = JsonDocument.Parse(File.ReadAllText("tests/fixtures/native-input-future-discard.json"));
        var proofs = file.RootElement.GetProperty("frames").EnumerateArray()
            .Select(x => x.Deserialize<CaptureDeliveryProof>(new JsonSerializerOptions { PropertyNameCaseInsensitive = true })!).ToArray();
        long request = proofs[0].RequestNs, deadline = request + 2_000_000_000, now = request;
        // Keep the rejected proof exactly as recorded. Only the later ordinary
        // delivery is explicitly rebound to this one operation for offline replay.
        proofs[1] = proofs[1] with { RequestNs = request, DeadlineNs = deadline };
        CapturedBgraFrame Frame(CaptureDeliveryProof p) => new(4, 4, 16, new byte[64],
            p.ReadbackCompletedNs, "", p.SourceNs, p.AcquisitionSequence, p, CaptureScopeEpoch: p.PoolEpoch);
        var window = new WindowBinding(1, 2, 3, 0);
        var scope = new ActionScope("fixture-match", 1, 1, 100, 100, "AUCTION_READY", "fixture-lease", deadline,
            window, 0, 1, now, true, true, true, true, false, false)
            { MatchGeneration = 1, ObservationSessionId = "input-capture-fixture" };
        NativeDomainFrame? Adapt(CapturedBgraFrame f) => WgcDomainCaptureAdapter.FromIndependentCapture(f, scope,
            new(4, 4, 0, 0), request, now, window, proofs[0].PoolEpoch);
        now = proofs[0].ReadbackCompletedNs + 1;
        Require(proofs[0].Qualified && proofs[0].OriginStatus == "FUTURE_AT_READ" && Adapt(Frame(proofs[0])) is null,
            "REJECTED_REAL_FRAME_MUST_STAY_UNQUALIFIED");
        now = request;
        int calls = 0;
        var selected = WgcDomainCaptureAdapter.CaptureForInput((wait, req, end) => {
            var p = proofs[Math.Min(calls++, 1)]; now = p.ReadbackCompletedNs + 1_000_000; return Frame(p);
        }, request, deadline, () => now);
        Console.WriteLine($"rejected-frame replay calls={calls}, selected={selected.AcquisitionSequence}, qualified={Adapt(selected) is not null}");
        Require(calls == 2 && selected.AcquisitionSequence == 877 && Adapt(selected) is not null,
            "DISCARD_FUTURE_FRAME_AND_REQUIRE_NEW_STRICT_SUPPORT");
        foreach (bool changed in new[] { false, true })
        {
            now = request; calls = 0;
            var p = changed ? proofs[0] with { ReadbackSourceTicks = proofs[0].SourceTicks + 1 } : proofs[0];
            var rejected = WgcDomainCaptureAdapter.CaptureForInput((_, _, _) => {
                calls++; now = p.ReadbackCompletedNs + calls; return Frame(p);
            }, request, deadline, () => now);
            Require(calls == (changed ? 1 : 4) && Adapt(rejected) is null, "PERSISTENT_OR_CHANGED_MARKER_NEVER_QUALIFIES");
        }
        Console.WriteLine("PASS saved rejection remains invalid; only a new strict capture recovers; persistent/changed marker rejected; zero input");
    }
}
