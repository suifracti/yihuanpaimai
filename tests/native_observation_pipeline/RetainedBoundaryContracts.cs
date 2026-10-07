using System.Text.Json;
using WgcLiveHarness;

internal static class RetainedBoundaryContracts
{
    private sealed record Frame(int Id);
    public static void Run()
    {
        void Check(bool ok, string why) { if (!ok) throw new Exception(why); }
        var results = new List<object>();
        foreach (var stock in new[] { 0, 1, 2 })
        {
            long now = 10; int inventory = stock, live = 0, takes = 0;
            bool empty = false, returnedBuffers = false;
            var released = new List<int>(); var observed = new List<string>();
            var trace = new List<DeliveryBoundaryOperation>();
            Frame? Take()
            {
                takes++;
                if (!empty)
                {
                    if (inventory > 0) { inventory--; live++; return new Frame(takes); }
                    Check(live == stock && released.Count == 0, "buffer returned before empty witness");
                    empty = true; observed.Add("empty"); return null;
                }
                Check(live == 0 && released.Count == stock && returnedBuffers,
                    "post-boundary take preceded buffer cleanup");
                observed.Add("delivered"); live++; return new Frame(99);
            }
            void Release(Frame f)
            {
                Check(!released.Contains(f.Id), "double release");
                released.Add(f.Id); live--; observed.Add("release-" + f.Id);
                // Returning a buffer can immediately refill the pool under continuous production.
                inventory++; returnedBuffers = true;
            }
            if (stock == 0) returnedBuffers = true;
            var chosen = DeliveredFrameSelector.Select(Take, Release, _ => { }, _ => true,
                () => ++now, () => false, 1, 1000, out var boundary, out var before, out var after,
                out var complete, out var drain, out var held, trace.Add);
            Check(chosen.Id == 99 && drain == stock + 1 && held == stock
                && boundary <= complete && complete <= before && before <= after, "bad witness order");
            Check(trace.FindIndex(e => e.Stage == "empty-boundary") < trace.FindIndex(e => e.Stage == "release-completed")
                && trace.FindIndex(e => e.Stage == "release-completed") < trace.FindIndex(e => e.Stage == "post-release-delivery"),
                "logged boundary/release/delivery order differs from observed ownership");
            Check(live == 1 && !released.Contains(99), "selected frame released before caller ownership");
            Release(chosen); Check(live == 0 && released.Count == stock + 1, "caller release leaked");
            results.Add(new { test = "continuous-refill-success", stock, takes, released, observed, trace, passed = true });
        }

        foreach (var fault in new[] { "third-nonempty", "drained-throws", "take-throws", "clock-throws",
            "cancel-held", "deadline-held", "release-throws", "trace-throws", "release-trace-throws",
            "cancel-selected", "cancel-selected-release-throws", "wait-throws" })
        {
            long now = 10; int takes = 0; bool cancel = false, clockFault = false, expired = false;
            var acquired = new List<int>(); var released = new List<int>();
            var trace = new List<DeliveryBoundaryOperation>(); Exception? failure = null;
            Frame? Take()
            {
                takes++;
                if (fault == "take-throws" && takes == 2) throw new ApplicationException("take-fault");
                if (takes == 3 && fault != "third-nonempty") return null;
                if (fault == "wait-throws" && takes > 3) return null;
                acquired.Add(takes);
                if (takes == 2 && fault == "cancel-held" || takes == 4 && fault.StartsWith("cancel-selected")) cancel = true;
                if (takes == 1 && fault == "clock-throws") clockFault = true;
                if (takes == 2 && fault == "deadline-held") expired = true;
                return new Frame(takes);
            }
            void Release(Frame f)
            {
                Check(!released.Contains(f.Id), "double release on " + fault);
                released.Add(f.Id);
                if (fault == "release-throws" && f.Id == 1) throw new ApplicationException("dispose-fault");
                if (fault == "cancel-selected-release-throws" && f.Id == 4) throw new ApplicationException("selected-dispose-fault");
            }
            try
            {
                DeliveredFrameSelector.Select(Take, Release, _ => {
                    if (fault == "drained-throws") throw new ApplicationException("property-fault");
                }, _ => throw new ApplicationException("wait-fault"), () => {
                    if (clockFault) throw new ApplicationException("clock-fault");
                    return expired ? 1000 : ++now;
                }, () => cancel, 1, 1000, out _, out _, out _, out _, out _, out _, e => {
                    trace.Add(e);
                    if (fault == "trace-throws" && e.Stage == "drain-take-after") throw new ApplicationException("log-fault");
                    if (fault == "release-trace-throws" && e.Stage == "release-before") throw new ApplicationException("release-log-fault");
                });
            }
            catch (Exception ex) { failure = ex; }
            Check(failure is not null && acquired.SequenceEqual(released), "failure leaked/released twice: " + fault);
            if (fault == "third-nonempty") Check(takes == 3 && failure!.Message == "POOL_BOUNDARY_UNPROVEN", "third frame retried");
            if (fault == "clock-throws") Check(failure!.Message == "clock-fault", "cleanup hid first failure");
            if (fault == "cancel-selected-release-throws") Check(failure is OperationCanceledException, "cleanup hid cancel");
            if (fault == "release-throws") Check(takes == 3 && released.Count == 2
                && failure!.Message == "DELIVERY_BUFFER_RELEASE_FAILED", "failed cleanup continued selection");
            results.Add(new { test = fault, takes, acquired, released, firstFailure = failure!.Message, trace, passed = true });
        }
        Console.WriteLine(JsonSerializer.Serialize(new { passed = true, gameCapture = false, gameInput = false, results },
            new JsonSerializerOptions { WriteIndented = true }));
    }
}
