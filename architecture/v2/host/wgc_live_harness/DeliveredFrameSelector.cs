using NteHost.Protocol;

namespace WgcLiveHarness;

internal sealed record DeliveryBoundaryOperation(string Stage, long AtNs, int Ordinal,
    int HeldCount, bool? FrameAvailable = null, string? Error = null);

// Only proves pool delivery after one observed empty boundary, never producer rendering.
internal static class DeliveredFrameSelector
{
    public static T Select<T>(Func<T?> take, Action<T> release, Action<T> drained,
        Func<int, bool> wait, Func<long> clock, Func<bool> stopped,
        long request, long deadline, out long barrier, out long before, out long after,
        out long releaseCompleted, out int drainTakes, out int boundaryHeldCount,
        Action<DeliveryBoundaryOperation>? trace = null) where T : class
    {
        long Available()
        {
            if (stopped()) throw new OperationCanceledException("delivery-stopped");
            var now = clock();
            if (now < request) throw new InvalidOperationException("DELIVERY_LOCAL_CLOCK_ORDER");
            if (now >= deadline) throw new TimeoutException("DELIVERY_DEADLINE");
            if (stopped()) throw new OperationCanceledException("delivery-stopped");
            return now;
        }
        barrier = before = after = releaseCompleted = 0;
        drainTakes = boundaryHeldCount = 0;
        var held = new List<T>(3); // Third non-null is owned for cleanup, never accepted.
        Exception? primary = null;
        try
        {
            for (var n = 0; n < 3; n++)
            {
                var start = Available();
                trace?.Invoke(new("drain-take-before", start, n + 1, held.Count));
                var old = take();
                // Own it before clocks, callbacks or cancellation can throw.
                if (old is not null) held.Add(old);
                drainTakes++;
                var end = Available();
                trace?.Invoke(new("drain-take-after", end, n + 1, held.Count, old is not null));
                if (old is null)
                {
                    barrier = end; boundaryHeldCount = held.Count;
                    trace?.Invoke(new("empty-boundary", barrier, drainTakes, held.Count, false));
                    break;
                }
                if (n == 2) throw new InvalidOperationException("POOL_BOUNDARY_UNPROVEN");
                drained(old);
                Available();
            }
        }
        catch (Exception ex) { primary = ex; throw; }
        finally
        {
            Exception? cleanup = null;
            for (var i = 0; i < held.Count; i++)
            {
                // A throwing clock/logger must not prevent Dispose of this or later frames.
                try { trace?.Invoke(new("release-before", clock(), i + 1, held.Count)); }
                catch (Exception ex) { cleanup ??= ex; }
                Exception? releaseError = null;
                try { release(held[i]); }
                catch (Exception ex) { cleanup ??= ex; releaseError = ex; }
                try { trace?.Invoke(new("release-after", clock(), i + 1, held.Count,
                    Error: releaseError?.GetType().Name)); }
                catch (Exception ex) { cleanup ??= ex; }
            }
            held.Clear(); // Each release attempted once; failed release is never retried.
            try
            {
                releaseCompleted = clock();
                trace?.Invoke(new("release-completed", releaseCompleted, drainTakes, 0,
                    Error: cleanup?.GetType().Name));
            }
            catch (Exception ex) { cleanup ??= ex; }
            if (cleanup is not null && primary is null)
                throw new InvalidOperationException("DELIVERY_BUFFER_RELEASE_FAILED", cleanup);
        }
        if (barrier == 0) throw new InvalidOperationException("POOL_BOUNDARY_UNPROVEN");
        while (true)
        {
            before = Available();
            var frame = take();
            var transferred = false;
            Exception? selectionFailure = null;
            try
            {
                after = Available();
                if (frame is null) { wait((int)Math.Min(50, Math.Max(1, (deadline - after) / 1_000_000))); continue; }
                trace?.Invoke(new("post-release-delivery", after, 0, 0, true));
                transferred = true;
                return frame;
            }
            catch (Exception ex) { selectionFailure = ex; throw; }
            finally
            {
                if (frame is not null && !transferred)
                {
                    try { release(frame); }
                    catch (Exception ex) when (selectionFailure is not null)
                    {
                        // Keep the first rejection while recording cleanup failure; never retry Dispose.
                        try { trace?.Invoke(new("selected-release-failed", clock(), 0, 0, Error: ex.GetType().Name)); }
                        catch { }
                    }
                }
            }
        }
    }
}
