using System;

namespace WgcLiveHarness;

/// <summary>
/// Selects an unread queued frame newer than one fixed request timestamp.
/// A successful return transfers ownership to the caller; every other dequeued
/// frame is released here. This helper performs no pixel readback or window query.
/// </summary>
internal static class RequestFrameSelector
{
    public static long DeadlineForRequest(int timeoutMs, long requestNs, long absoluteWorkDeadlineNs)
    {
        if (timeoutMs <= 0) throw new ArgumentOutOfRangeException(nameof(timeoutMs));
        if (requestNs <= 0) throw new ArgumentOutOfRangeException(nameof(requestNs));
        if (absoluteWorkDeadlineNs <= 0) throw new ArgumentOutOfRangeException(nameof(absoluteWorkDeadlineNs));
        return Math.Min(absoluteWorkDeadlineNs, checked(requestNs + timeoutMs * 1_000_000L));
    }

    public static T Select<T>(Func<T?> takeNext, Func<T, long> sourceTimestamp,
        Action<T> discard, Func<int, bool> waitForFrame, Func<long> clock,
        Func<bool> stopped, long requestNs, long deadlineNs,
        out int discardedQueuedFrames) where T : class
    {
        discardedQueuedFrames = 0;
        ArgumentNullException.ThrowIfNull(takeNext);
        ArgumentNullException.ThrowIfNull(sourceTimestamp);
        ArgumentNullException.ThrowIfNull(discard);
        ArgumentNullException.ThrowIfNull(waitForFrame);
        ArgumentNullException.ThrowIfNull(clock);
        ArgumentNullException.ThrowIfNull(stopped);
        if (requestNs <= 0 || requestNs > clock())
            throw new ArgumentOutOfRangeException(nameof(requestNs), "Request timestamp must be positive and not in the future.");
        if (deadlineNs <= 0)
            throw new ArgumentOutOfRangeException(nameof(deadlineNs), "Deadline must be positive.");

        long CheckAvailable()
        {
            if (stopped()) throw new OperationCanceledException("Request-frame selection was stopped.");
            var now = clock();
            // Clock/availability callbacks can themselves coincide with a stop request.
            if (stopped()) throw new OperationCanceledException("Request-frame selection was stopped.");
            if (now >= deadlineNs) throw new TimeoutException("Request-frame selection reached its original deadline.");
            return now;
        }

        while (true)
        {
            CheckAvailable();
            T? frame = null;
            var transferred = false;
            try
            {
                frame = takeNext();
                CheckAvailable();
                if (frame is null)
                {
                    var remainingNs = deadlineNs - CheckAvailable();
                    // Divide before rounding up so a large valid deadline cannot overflow.
                    var remainingMs = remainingNs / 1_000_000L
                        + (remainingNs % 1_000_000L == 0 ? 0 : 1);
                    var waitMs = (int)Math.Min(50L, remainingMs);
                    // FrameArrived is a wake-up hint, not a queue count. A false
                    // result consumes only this slice, never starts a new timeout.
                    waitForFrame(waitMs);
                    CheckAvailable();
                    continue;
                }

                var sourceNs = sourceTimestamp(frame);
                var afterSourceNs = CheckAvailable();
                if (sourceNs <= 0)
                    throw new InvalidOperationException("Queued frame source timestamp is unavailable.");
                if (sourceNs > afterSourceNs)
                    throw new InvalidOperationException(
                        $"Queued frame source timestamp is in the future. "
                        + $"sourceNs={sourceNs}; observedNs={afterSourceNs}; "
                        + $"aheadNs={sourceNs - afterSourceNs}; requestNs={requestNs}; deadlineNs={deadlineNs}");
                if (sourceNs <= requestNs)
                {
                    // Remove local ownership before releasing: a failing release
                    // must not cause a second disposal from the finally block.
                    var oldFrame = frame;
                    frame = null;
                    discard(oldFrame);
                    discardedQueuedFrames++;
                    CheckAvailable();
                    // Another queued frame can already exist even when multiple
                    // arrivals were coalesced into a single AutoResetEvent signal.
                    continue;
                }

                CheckAvailable();
                transferred = true;
                return frame;
            }
            finally
            {
                if (frame is not null && !transferred) discard(frame);
            }
        }
    }
}
