using System;
using System.Diagnostics;

namespace NteHost.Protocol;

/// <summary>
/// WINDOWS_QPC_NANOSECONDS clock domain. Both peers must timestamp on the same
/// hardware QueryPerformanceCounter so that cross-process deltas (notably the
/// crash-marker -> detection latency) are meaningful.
///
/// .NET side: Stopwatch.GetTimestamp() is QPC-backed.
/// Python side: time.perf_counter_ns() is QPC-backed on Windows.
/// </summary>
public static class ProtocolClock
{
    public static long NowNs()
    {
        var ticks = Stopwatch.GetTimestamp();
        return TicksToNs(ticks);
    }

    /// <summary>
    /// Converts QPC ticks to nanoseconds without overflowing Int64.
    ///
    /// The naive `ticks * 1_000_000_000 / frequency` overflows as soon as the
    /// machine has been up for a few hours (ticks ~1.5e14 with a 10 MHz counter
    /// gives 1.5e23, far past Int64.MaxValue) and silently produces negative
    /// timestamps. Splitting into whole seconds plus a bounded remainder keeps
    /// every intermediate product below 1e16.
    /// </summary>
    public static long TicksToNs(long ticks)
    {
        var frequency = Stopwatch.Frequency;
        var seconds = ticks / frequency;
        var remainder = ticks % frequency;
        return seconds * 1_000_000_000L + remainder * 1_000_000_000L / frequency;
    }

    public static double NsToMs(long ns) => ns / 1_000_000.0;

    public static double DeltaMs(long fromNs, long toNs) => NsToMs(toNs - fromNs);

    public static long Frequency => Stopwatch.Frequency;
}
